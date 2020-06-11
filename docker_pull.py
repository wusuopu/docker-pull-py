#!/usr/bin/env python
# encoding: utf-8

import os
import sys
import gzip
from io import BytesIO
import json
import hashlib
import shutil
import requests
import tarfile
import urllib3
import copy
urllib3.disable_warnings()


def mkdir(path):
    if (not os.path.exists(path)):
        os.mkdir(path)


def parse_image(image_name):
    """
    解析 image name
    """
    repo = 'library'
    tag = 'latest'
    imgparts = image_name.split('/')
    try:
        img, tag = imgparts[-1].split('@')
    except ValueError:
        try:
            img, tag = imgparts[-1].split(':')
        except ValueError:
            img = imgparts[-1]
    # Docker client doesn't seem to consider the first element as a potential registry unless there is a '.' or ':'
    if len(imgparts) > 1 and ('.' in imgparts[0] or ':' in imgparts[0]):
        # 第三方仓库
        registry = imgparts[0]
        repo = '/'.join(imgparts[1:-1])
        slug = '%s/%s/%s' % (registry, repo, img)
    else:
        registry = 'registry-1.docker.io'
        if len(imgparts[:-1]) != 0:
            repo = '/'.join(imgparts[:-1])
            slug = '%s/%s' % (repo, img)
        else:
            repo = 'library'
            slug = '%s' % (img)
    repository = '{}/{}'.format(repo, img)
    return {
        'tag': tag, 'repo': repo,
        'repository': repository,
        'registry': registry,
        'img': img, 'slug': slug
    }


def get_auth_url(docker_image):
    auth_url = 'https://auth.docker.io/token'
    reg_service = 'registry.docker.io'
    resp = requests.get('https://{}/v2/'.format(docker_image['registry']), verify=False)
    if resp.status_code == 401:
        auth_url = resp.headers['WWW-Authenticate'].split('"')[1]
        try:
            reg_service = resp.headers['WWW-Authenticate'].split('"')[3]
        except IndexError:
            reg_service = ""
    return {'auth_url': auth_url, 'reg_service': reg_service}


def get_auth_head(docker_image, auth, scope):
    resp = requests.get(
        '{}?service={}&scope=repository:{}:pull'.format(
            auth['auth_url'], auth['reg_service'], docker_image['repository']
        ), verify=False
    )
    access_token = resp.json()['token']
    auth_head = {'Authorization':'Bearer '+ access_token, 'Accept': scope}
    return auth_head


# ======================== manifest start ====================================
def dump_manifests(manifests):
    for manifest in manifests:
        for key, value in manifest["platform"].items():
            sys.stdout.write('{}: {}, '.format(key, value))
        print('digest: {}'.format(manifest["digest"]))


def fetch_manifest_list(docker_image, auth):
    auth_head = get_auth_head(
        docker_image, auth,
        'application/vnd.docker.distribution.manifest.list.v2+json'
    )
    resp = requests.get(
        'https://{}/v2/{}/manifests/{}'.format(
            docker_image['registry'], docker_image['repository'], docker_image['tag']
        ),
        headers=auth_head, verify=False
    )
    if (resp.status_code != 200):
        print(resp.content)
        raise Exception('fetch_manifest_list')

    manifests = resp.json()['manifests']
    return manifests


def fetch_manifest(docker_image, auth):
    auth_head = get_auth_head(
        docker_image, auth,
        'application/vnd.docker.distribution.manifest.v2+json'
    )
    resp = requests.get(
        'https://{}/v2/{}/manifests/{}'.format(
            docker_image['registry'], docker_image['repository'], docker_image['tag']
        ),
        headers=auth_head, verify=False
    )
    if (resp.status_code != 200):
        print('[-] Cannot fetch manifest for {} [HTTP {}]'.format(docker_image['repository'], resp.status_code))
        print(resp.content)

        dump_manifests(fetch_manifest_list(docker_image, auth))
        raise Exception('fetch_manifest')

    return resp.json()
# ======================== manifest end ====================================


# ======================== Layers start ====================================
def fetch_blob(docker_image, auth, manifest):
    auth_head = get_auth_head(
        docker_image, auth,
        'application/vnd.docker.distribution.manifest.v2+json'
    )
    resp = requests.get(
        'https://{}/v2/{}/blobs/{}'.format(
            docker_image['registry'], docker_image['repository'], manifest['config']['digest']
        ),
        headers=auth_head, verify=False
    )
    return resp.json()


def download_layer_blob(docker_image, auth, layer, layerdir):
    """
    下载 manifest 的 layer 文件
    """
    layer_filename = os.path.join(layerdir, 'layer_gzip.tar')
    blob_digest = layer['digest']

    sys.stdout.write(blob_digest[7:19] + ': Downloading...')
    sys.stdout.flush()

    auth_head = get_auth_head(
        docker_image, auth,
        'application/vnd.docker.distribution.manifest.v2+json'
    )
    if (os.path.exists(layer_filename)):
        # 断点续传
        size = os.stat(layer_filename).st_size
        if size == layer['size']:
            print('%s 已存在' % (layer_filename))
            return layer_filename
        auth_head['Range'] = 'bytes=%d-' % (size)

    bresp = requests.get(
        'https://{}/v2/{}/blobs/{}'.format(
            docker_image['registry'], docker_image['repository'], blob_digest
        ),
        headers=auth_head,
        stream=True,
        verify=False
    )
    if (bresp.status_code >= 400):
        print('\rERROR: Cannot download layer {} [HTTP {}]'.format(blob_digest[7:19], bresp.status_code))
        print(bresp.content)
        raise Exception('download_layer_blob')

    bresp.raise_for_status()
    unit = int(bresp.headers['Content-Length']) / 50
    acc = 0
    nb_traits = 0
    progress_bar(blob_digest, nb_traits)
    # 保存 layer
    with open(layer_filename, "ab+") as fp:
        for chunk in bresp.iter_content(chunk_size=8192):
            if chunk:
                fp.write(chunk)
                acc = acc + 8192
                if acc > unit:
                    nb_traits = nb_traits + 1
                    progress_bar(blob_digest, nb_traits)
                    acc = 0

    sys.stdout.flush()
    print("\r{}: Pull complete [{}]".format(blob_digest[7:19], bresp.headers['Content-Length']))
    return layer_filename

# ======================== Layers end ====================================

# ======================== download start ====================================
def create_image_folder(docker_image):
    """
    创建临时目录，用于保存下载文件
    """
    imgdir = 'tmp_{}_{}'.format(docker_image['img'], docker_image['tag'].replace(':', '@'))
    mkdir(imgdir)
    return imgdir


def progress_bar(digest, nb_traits):
    """
    显示下载进度条
    """
    sys.stdout.write('\r' + digest[7:19] + ': Downloading [')
    for i in range(0, nb_traits):
        if i == nb_traits - 1:
            sys.stdout.write('>')
        else:
            sys.stdout.write('=')
    for i in range(0, 49 - nb_traits):
        sys.stdout.write(' ')
    sys.stdout.write(']')
    sys.stdout.flush()


def decompress_all_layers(all_layer_dirs):
    """
    解压所有的 layer gzip 文件
    """
    for layerdir in all_layer_dirs:
        tar_file = os.path.join(layerdir, 'layer.tar')
        gzip_file = os.path.join(layerdir, 'layer_gzip.tar')
        if not os.path.exists(gzip_file):
            continue
        print('准备解压 %s' % (gzip_file))
        with open(tar_file, "wb") as fp:
            unzLayer = gzip.open(gzip_file,'rb')
            shutil.copyfileobj(unzLayer, fp)
            unzLayer.close()
        # 解压之后删除 gzip 文件
        os.remove(gzip_file)


def pull_image(docker_image, auth, manifest, blob):
    parentid=''
    imgdir = create_image_folder(docker_image)

    # 保存 blob 信息
    digest = manifest['config']['digest']
    with open(os.path.join(imgdir, digest[7:]+'.json'), 'wb') as fp:
        json.dump(blob, fp, indent=2)

    content = [{
        'Config': digest[7:] + '.json',
        'RepoTags': [ "%s:%s" % (docker_image['slug'], docker_image['tag']) ],
        'Layers': [ ]
    }]

    i = 1
    fake_layerid = ''
    all_layers = []
    for layer in manifest['layers']:
        blob_digest = layer['digest']
        fake_layerid = hashlib.sha256((parentid+'\n'+blob_digest+'\n').encode('utf-8')).hexdigest()
        layerdir = os.path.join(imgdir, fake_layerid)
        mkdir(layerdir)
        all_layers.append(layerdir)

        # Creating VERSION file
        with open(os.path.join(layerdir, 'VERSION'), 'w') as fp:
            fp.write('1.0')

        download_layer_blob(docker_image, auth, layer, layerdir)
        content[0]['Layers'].append(os.path.join(fake_layerid, 'layer.tar'))
        # 在 layer tar 目录下创建一个 json 文件 =======================
        with open(os.path.join(layerdir, 'json'), 'w') as fp:
            if i == len(manifest['layers']):
                # 最后一个 layer 文件 =================================
                json_obj = copy.deepcopy(blob)
                del json_obj['history']
                try:
                    del json_obj['rootfs']
                except: # Because Microsoft loves case insensitiveness
                    del json_obj['rootfS']
            else:
                # 不是最后一个 layer 文件 使用空的 json ================
                json_obj = {
                    'container_config': {
                        'AttachStderr': False,
                        'AttachStdin': False,
                        'AttachStdout': False,
                        'Cmd': None,
                        'Domainname': '',
                        'Entrypoint': None,
                        'Env': None,
                        'Hostname': '',
                        'Image': '',
                        'Labels': None,
                        'OnBuild': None,
                        'OpenStdin': False,
                        'StdinOnce': False,
                        'Tty': False,
                        'User': '',
                        'Volumes': None,
                        'WorkingDir': ''
                    },
                    'created': '1970-01-01T00:00:00Z'
                }

            json_obj['id'] = fake_layerid
            if parentid:
                json_obj['parent'] = parentid
            parentid = json_obj['id']
            json.dump(json_obj, fp, indent=2)
        i += 1

    # 解压 gzip 文件为 tar 文件 =======================================
    decompress_all_layers(all_layers)
    # 创建 manifest 文件
    with open(os.path.join(imgdir, 'manifest.json'), 'w') as fp:
        json.dump(content, fp, indent=2)
    with open(os.path.join(imgdir, 'repositories'), 'w') as fp:
        json.dump({
            docker_image['slug']: { docker_image['tag']: fake_layerid }
        }, fp, indent=2)

    # 创建 image tar 文件
    docker_tar = docker_image['repository'].replace('/', '_')  + '.tar'
    print('create image archive...')
    tar = tarfile.open(docker_tar, "w")
    tar.add(imgdir, arcname=os.path.sep)
    tar.close()
    print('\rDocker image pulled: ' + docker_tar)
# ======================== download end ====================================


def print_manifest(image_name):
    docker_image = parse_image(image_name)
    auth = get_auth_url(docker_image)

    print(json.dumps(fetch_manifest_list(docker_image, auth), indent=2))
    manifest = fetch_manifest(docker_image, auth)
    print(json.dumps(manifest, indent=2))
    blob = fetch_blob(docker_image, auth, manifest)
    print(json.dumps(blob, indent=2))


def main(image_name):
    docker_image = parse_image(image_name)
    auth = get_auth_url(docker_image)

    manifest = fetch_manifest(docker_image, auth)
    blob = fetch_blob(docker_image, auth, manifest)
    pull_image(docker_image, auth, manifest, blob)


if __name__ == '__main__':
    if len(sys.argv) != 2 :
        print('Usage:\n\t%s [registry/][repository/]image[:tag|@digest]\n' % (sys.argv[0]))
        exit(1)

    main(sys.argv[1])
