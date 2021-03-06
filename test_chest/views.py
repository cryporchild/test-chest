import json

from django.contrib.auth.models import User, Group
from django.core.exceptions import FieldError

from rest_framework import filters, viewsets
from rest_framework.decorators import detail_route, list_route
from rest_framework.exceptions import ParseError
from rest_framework.response import Response

import xml.etree.ElementTree

from .models import Tag, TestCase, TestSuite, Result
from .serializers import (
    UserSerializer, GroupSerializer, TagSerializer, TestCaseSerializer,
    TestSuiteSerializer,
)


class FilteringModelViewSet(viewsets.ModelViewSet):

    def get_queryset(self):
        filters = self.request.query_params.dict().copy()
        for filter_name in ['ordering', 'limit', 'offset']:
            if filter_name in filters:
                del filters[filter_name]
        try:
            return self.queryset.filter(**filters).distinct()
        except FieldError as error:
            raise ParseError(error.args)


class UserViewSet(FilteringModelViewSet):
    """
    API endpoint that allows users to be viewed or edited.
    """
    queryset = User.objects.all().order_by('-date_joined')
    serializer_class = UserSerializer
    filter_backends = (filters.OrderingFilter,)
    ordering_fields = ('date_joined')


class GroupViewSet(FilteringModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """
    queryset = Group.objects.all().order_by('id')
    serializer_class = GroupSerializer
    filter_backends = (filters.OrderingFilter,)
    ordering_fields = ('id')


class TagViewSet(FilteringModelViewSet):
    queryset = Tag.objects.all().order_by('name').distinct()
    serializer_class = TagSerializer
    filter_backends = (filters.OrderingFilter,)
    ordering_fields = ('name')


class TestCaseViewSet(FilteringModelViewSet):
    queryset = TestCase.objects.all().order_by('uploaded')
    serializer_class = TestCaseSerializer
    filter_backends = (filters.OrderingFilter,)
    ordering_fields = (
        'name', 'classname', 'file', 'line', 'time', 'uploaded', 'tags',
        'testsuite',
    )


class TestSuiteViewSet(FilteringModelViewSet):
    queryset = TestSuite.objects.all().order_by('uploaded')
    serializer_class = TestSuiteSerializer
    filter_backends = (filters.OrderingFilter,)
    ordering_fields = ('name', 'time', 'uploaded')

    def _get_tags(self, request):
        tags = []
        if 'tags' in request.POST:
            tag_names = json.loads(request.POST['tags'])
            for tname in tag_names:
                tag = Tag(name=tname)
                tag.save()
                tags.append(tag)
        return tags

    def _create_test_case(self, test_case_xml, testsuite, tags):
        tc = TestCase(
            name=test_case_xml.get('name'),
            classname=test_case_xml.get('classname'),
            time=test_case_xml.get('time'),
            file=test_case_xml.get('file'),
            line=test_case_xml.get('line'),
            testsuite=testsuite,
        )
        # TODO: XFAIL, ERROR...
        failure = test_case_xml.find('failure')
        skipped = test_case_xml.find('skipped')
        if failure is not None:
            tc.result = Result.FAIL
            tc.message = failure.get('message')
            tc.traceback = failure.text
        elif skipped is not None:
            tc.result = Result.SKIP
            tc.message = skipped.get('message')
            tc.traceback = skipped.text
        else:
            tc.result = Result.PASS
        tc.save()
        if tags:
            tc.tags = tags
        return tc

    @list_route(methods=['post'])
    def upload_junit_xml(self, request):
        suites = []
        cases = []
        tags = self._get_tags(request)
        for _, fp in request.FILES.items():
            e = xml.etree.ElementTree.fromstring(fp.read())
            xml_suites = list(e.findall('testsuite'))
            if not xml_suites:
                xml_suites = [e]
            for s in xml_suites:
                suite = TestSuite(name=s.get('name'), time=s.get('time'))
                suite.save()
                for c in s.findall('testcase'):
                    self._create_test_case(c, suite, tags)
                suites.append(suite)
        return Response(TestSuiteSerializer(suites, context={'request': request}, many=True).data)
