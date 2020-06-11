#!/usr/bin/env python
# encoding: utf-8

import unittest
import docker_pull


class ParseImageTest(unittest.TestCase):
    def test_parse_image1(self):
        # 官方镜像
        ret = docker_pull.parse_image('node')
        self.assertEqual(ret['repo'], 'library')
        self.assertEqual(ret['tag'], 'latest')
        self.assertEqual(ret['registry'], 'registry-1.docker.io')
        self.assertEqual(ret['repository'], 'library/node')

        ret = docker_pull.parse_image('node:10-alpine')
        self.assertEqual(ret['repo'], 'library')
        self.assertEqual(ret['tag'], '10-alpine')
        self.assertEqual(ret['registry'], 'registry-1.docker.io')
        self.assertEqual(ret['repository'], 'library/node')

    def test_parse_image2(self):
        # 用户的镜像
        ret = docker_pull.parse_image('user/image')
        self.assertEqual(ret['repo'], 'user')
        self.assertEqual(ret['tag'], 'latest')
        self.assertEqual(ret['registry'], 'registry-1.docker.io')
        self.assertEqual(ret['repository'], 'user/image')

        ret = docker_pull.parse_image('user/image:tag')
        self.assertEqual(ret['repo'], 'user')
        self.assertEqual(ret['tag'], 'tag')
        self.assertEqual(ret['registry'], 'registry-1.docker.io')
        self.assertEqual(ret['repository'], 'user/image')

    def test_parse_image3(self):
        # 第三方仓库
        ret = docker_pull.parse_image('mcr.microsoft.com/windows/servercore')
        self.assertEqual(ret['repo'], 'windows')
        self.assertEqual(ret['tag'], 'latest')
        self.assertEqual(ret['registry'], 'mcr.microsoft.com')
        self.assertEqual(ret['repository'], 'windows/servercore')

        ret = docker_pull.parse_image('mcr.microsoft.com/windows/servercore:ltsc2016')
        self.assertEqual(ret['repo'], 'windows')
        self.assertEqual(ret['tag'], 'ltsc2016')
        self.assertEqual(ret['registry'], 'mcr.microsoft.com')
        self.assertEqual(ret['repository'], 'windows/servercore')

    def test_parse_image4(self):
        ret = docker_pull.parse_image('node@sha256:075012d2072be942e17da73a35278be89707266010fb6977bfc43dae5d492ab4')
        self.assertEqual(ret['repo'], 'library')
        self.assertEqual(ret['tag'], 'sha256:075012d2072be942e17da73a35278be89707266010fb6977bfc43dae5d492ab4')
        self.assertEqual(ret['registry'], 'registry-1.docker.io')
        self.assertEqual(ret['repository'], 'library/node')


if __name__ == '__main__':
    unittest.main()
