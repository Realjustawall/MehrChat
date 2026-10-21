"""Insert the isolated decoder after p4a generates its complete manifest.

The pinned p4a release supports application attributes, but no application-child
XML option. Its before_apk_assemble hook runs inside the generated distribution.
"""
from pathlib import Path
import os
import xml.etree.ElementTree as ET

ANDROID='http://schemas.android.com/apk/res/android'
NAME='{'+ANDROID+'}name'
SERVICE='org.mehrchat.preview.PreviewService'

def configure_manifest(path):
    path=Path(path)
    ET.register_namespace('android',ANDROID)
    tree=ET.parse(path);application=tree.getroot().find('application')
    if application is None:raise ValueError('Generated manifest lacks application')
    for node in list(application.findall('service')):
        if node.get(NAME)==SERVICE:application.remove(node)
    fragment=(Path(__file__).resolve().parents[1]/'android-preview-manifest.xml').read_text(encoding='utf-8')
    wrapper=ET.fromstring('<application xmlns:android="'+ANDROID+'">'+fragment+'</application>')
    service=wrapper.find('service')
    if service is None or service.get(NAME)!=SERVICE:raise ValueError('Invalid decoder declaration')
    if service.get('{'+ANDROID+'}isolatedProcess')!='true' or service.get('{'+ANDROID+'}exported')!='false':
        raise ValueError('Decoder service must be private and isolated')
    application.append(service)
    temporary=path.with_suffix('.tmp')
    tree.write(temporary,encoding='utf-8',xml_declaration=True)
    os.replace(temporary,path)

def before_apk_assemble(toolchain):
    configure_manifest('src/main/AndroidManifest.xml')
