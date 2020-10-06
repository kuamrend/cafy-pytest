'''
This plugin will cover all the cafy related plugin like email report
'''
import os
import sys
import subprocess
import platform
import smtplib
import getpass
import time
import zipfile
import shutil
import validators
import itertools
import html
import re
import requests
import json
import inspect
import yaml
import pytest
import traceback

from _pytest.terminal import TerminalReporter
from _pytest.runner import runtestprotocol, TestReport
from _pytest.mark import MarkInfo

from enum import Enum
from tabulate import tabulate
from pprint import pprint, pformat
from shutil import copyfile
from configparser import ConfigParser
from datetime import datetime
from collections import namedtuple, OrderedDict, defaultdict

from email.utils import COMMASPACE
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from jinja2 import Template

from logger.cafylog import CafyLog
from topology.topo_mgr.topo_mgr import Topology
from utils.cafyexception  import CafyException
from debug import DebugLibrary

from wrapt_timeout_decorator import timeout as wrapt_timeout

#Check with CAFYKIT_HOME or GIT_REPO or CAFYAP_REPO environment is set,
#if all are set, CAFYAP_REPO takes precedence
CAFY_REPO = os.environ.get("CAFYAP_REPO", None)
if CAFY_REPO is None:
    #If CAFYAP_REPO is not set, check if GIT_REPO or CAFYKIT_HOME is set
    #If both GIT_REPO and CAFYKIT_HOME are set, CAFYKIT_HOME takes precedence
    CAFY_REPO = os.environ.get("CAFYKIT_HOME", None)
    if CAFY_REPO:
        os.environ['CAFY_REPO'] = CAFY_REPO
    else:
        CAFY_REPO = os.environ.get("GIT_REPO", None)
        if CAFY_REPO:
            os.environ['CAFY_REPO'] = CAFY_REPO
            if os.path.exists(os.path.join(CAFY_REPO, 'work', 'pytest_cafy_config.yaml')):
                os.environ['CAFY_REPO'] = CAFY_REPO
                print('GIT_REPO variable has been set to correct repo')
            else:
                msg = 'GIT_REPO has not been set to correct repo'
                pytest.exit(msg)
else:
    os.environ['CAFY_REPO'] = CAFY_REPO

if not CAFY_REPO:
    msg = "Please set the environment variable GIT_REPO or CAFYKIT_HOME or CAFYAP_REPO "
    pytest.exit(msg)


cafy_args = os.environ.get('CAFY_ARGS')
if cafy_args:
    config = ConfigParser() # instantiate
    config.read(cafy_args) # parse existing file
    config_sections = config.sections()


@pytest.hookimpl(tryfirst=True)
def pytest_addoption(parser):
    yml = load_config_file()
    if 'email' in yml:
        email = yml['email']
        email_from = email.get('from')
        email_list = getpass.getuser()
        if 'domain' in email:
            email_list = "%s@%s" % (email_list, email['domain'])
            email_list = [email_list]
        try:
            smtp_server = email['via']['server']
            smtp_port = email['via']['port']
        except:
            smtp_server = 'localhost'
            smtp_port = 25
    else:
        email_from = None
        email_list = None
        smtp_server = 'localhost'
        smtp_port = 25

    group = parser.getgroup('terminal reporting')
    group.addoption('--mail-to', action='store', dest='email_list',
                    default=email_list, type=str, nargs='*',
                    help='send the email to specified email addresses')
    group.addoption('--mail-from', action='store', dest='email_from',
                    default=email_from,
                    help='email id with which email will be sent')
    group.addoption('--mail-from-passwd', action='store',
                    dest='email_from_passwd',
                    default=None,
                    help='password of email id given in --mailfrom')
    group.addoption('--smtp-server', action='store', dest='smtp_server',
                    default=smtp_server,
                    help='smtp server ip address/dns name e.g 127.0.0.1 or '
                         'localhost')
    group.addoption('--smtp-port', action='store', dest='smtp_port',
                    default=smtp_port, type=int,
                    help='smtp server port e.g 25')
    group.addoption('--no-email', dest='no_email', action='store_true',
                    help='if specified no email will be sent')
    group.addoption('--mail-if-fail', dest='mail_if_fail', action='store_true',
                    help='if specified, email will be sent only total testcase = passed testcases')

    group = parser.getgroup('Work Dir Path')
    group.addoption('--work-dir', dest="workdir", metavar="DIR", default=None,
                    help="Path for work dir")

    group.addoption('-R','--report-dir', dest="reportdir",
                    metavar="DIR",
                    default=None,
                    help="Path for report dir")

    group = parser.getgroup('Testbed Options')
    group.addoption('-T', '--topology-file', action='store', dest='topology_file',
                    metavar='topology_file',
                    type=lambda x: is_valid_param(x, file_type='topology_file'),
                    help='Filename of your testbed')

    group.addoption('-I', '--test-input-file', action='store', dest='test_input_file',
                    metavar='test_input_file',
                    type=lambda x: is_valid_param(x, file_type='input_file'),
                    help='Filename of your test input file')

    group.addoption('--tag-file', action='store', dest='tag_file',
                    metavar='tagmap_file',
                    type=lambda x: is_valid_param(x, file_type='tagmap_file'),
                    help='Filename of your tag map')

    group.addoption('--selective-test-file', action='store', dest='selective_test_file',
                    metavar='selective_test_file',
                    type=lambda x: is_valid_param(x, file_type='selective_test_file'),
                    help='Filename of your selective testcases')

    group.addoption('--commit-check', dest='commit_check', action='store_true',
                    help='Variable to set commit check option, default is False')

    group.addoption('--enable-live-update', dest='enable_live_update', action='store_true',
                    help='Variable to enable live logging the status of testcases, default is False')

    group = parser.getgroup('Cafykit Debug ')
    group.addoption('--debug-enable', dest='debug_enable', action='store_true',
                    help='Variable to enable cafykit debug, default is False')

    group = parser.getgroup('Script Arguments')
    group.addoption('--script-args', action='store', dest='script_args',
                    metavar='script_args', default="{'__nothing__': None}",
                    type=lambda x: is_valid_cafyarg(x),
                    help=' For your additional cafy arguments, A yaml file or\
                     a string of dict')


    group = parser.getgroup('Mongo Device')
    group.addoption('--mongo-learn', dest='mongo_learn', action='store_true',
                    help='Variable to enable mongo learning, default is False')
    group.addoption('--mongo-read', dest='mongo_read', action='store_true',
                    help='Variable to enable mongo read, default is False')
    group.addoption('--mongo-mode', action='store', dest='mongo_mode',
            metavar='mongo_mode',
            help='Variable to enable mongo read/write, default is None')

def is_valid_param(arg, file_type=None):
    if not arg:
        pytest.exit("%s not provided!" % file_type)
    if not os.path.exists(arg):
        #If not a valid file, check if it is a valid url
        if validators.url(arg):
            return arg
        else:
            pytest.exit("%s either doesn't exist or is an invalid url!" % arg)
    else:
        # pytest.topology_file = arg # Set the global namespace variable
        return arg  # It is important to add a return statement, if not given,
        # by default, it returns None and then your
        # config.option.topology_file will be set to None
        # return open(arg, 'r')  # return an open file handle


def is_valid_cafyarg(arg):
    #if block is executed when arg is not a file,instead it is string of dict
    if not os.path.exists(arg):
        eval(arg)
        argdict = yaml.load(arg)
        CafyLog.script_args = argdict
    else:
        #else block is executed when arg is a file
        script_arg_file = is_valid_param(arg)
        CafyLog.script_args = script_arg_file
    return arg


def load_config_file(filename=None):
    _filename = filename
    if not _filename:
        git_repo = os.getenv("GIT_REPO", None)
    if git_repo:
        try:
            _filename = os.path.join(
                git_repo, "work", "pytest_cafy_config.yaml")
            with open(_filename, 'r') as stream:
                return (yaml.load(stream))
        except:
            return {}


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    config._environment = []
    email_list = config.option.email_list
    email_from = config.option.email_from
    email_from_passwd = config.option.email_from_passwd
    smtp_server = config.option.smtp_server
    smtp_port = config.option.smtp_port
    no_email = config.option.no_email
    cafykit_debug_enable = config.option.debug_enable
    CafyLog.topology_file = config.option.topology_file
    CafyLog.test_input_file = config.option.test_input_file
    CafyLog.tag_file = config.option.tag_file
    CafyLog.mongomode=config.option.mongo_mode
    script_list = config.option.file_or_dir
    # register additional markers
    config.addinivalue_line("markers", "Future(name): mark test that are planned for future")
    config.addinivalue_line("markers", "Feature(name): mark feature of a testcase")
    config.addinivalue_line("markers", "autofail(name): mark test to Fail when  this testcase has triggered autofail condition")

    if script_list:
        script_path = script_list[0]
        if '::' in script_path:
            script_path = script_path.split('::')[0]
        CafyLog.script_path = os.path.abspath(script_path)

        script_name = os.path.basename(script_list[0]).replace('.py', '')
        #If someone gives the script in the format
        #moduleName::className::testcaseName to execute only a specific testcase
        if '::' in script_name:
            script_name = script_name.split('::')[0]
        CafyLog.module_name = script_name
        _current_time = get_datentime()
        pid = os.getpid()
        work_dir_name = "%s_%s_p%s" % (script_name,_current_time, pid )

        if not config.option.reportdir:
            #If workdir option is set, execute the if block and if not given,
            #execute the else block where the workdir will be set to
            #GIT_REPO/work/archive
            if config.option.workdir:
                if os.path.exists(config.option.workdir):
                    custom_workdir = config.option.workdir
                    work_dir = custom_workdir
                else:
                    print('workdir path not found: {}'.format(config.option.workdir))
                    pytest.exit('workdir path not found')
            else:
                if CAFY_REPO:
                    work_dir = os.path.join(CAFY_REPO, 'work', "archive", work_dir_name)
        else:
            if os.path.exists(config.option.reportdir):
                work_dir = os.path.join(config.option.reportdir, work_dir_name)
            else:
                print('reportdir path not found: {}'.format(config.option.reportdir))
                pytest.exit('reportdir path not found')

        CafyLog.work_dir = work_dir
        #Set CafyLog.work_dir option for all.log
        CafyLog.work_dir = work_dir
        _setup_env()

        #Copy topology-file if given to work_dir
        if config.option.topology_file:
            if os.path.exists(config.option.topology_file):
                topo_file = os.path.abspath(config.option.topology_file)
                topo_filename = os.path.basename(config.option.topology_file)
                topo_file_path = os.path.join(work_dir, topo_filename)
                copyfile(config.option.topology_file, topo_file_path)
                os.chmod(topo_file_path, 0o775)

                #If topology_file is given, and  attribute is present,
                #then, save this attibute in a variable called debug_server which will be
                #host to run debug services like registrationa and collector
                topo_obj = Topology(CafyLog.topology_file)
                debug_server = topo_obj.get_debug_server_name()
                logstash_port = topo_obj.get_logstash_port()
                logstash_server_name = topo_obj.get_logstash_server_name()

                if logstash_server_name is not None:
                    CafyLog.logstash_server = logstash_server_name

                if logstash_port is not None:
                    CafyLog.logstash_port = logstash_port

                if debug_server is not None:
                    CafyLog.debug_server = debug_server
                    log = CafyLog("cafy")
                    log.info("CafyLog.debug_server : %s" %CafyLog.debug_server )
            else:
                #TODO: Address how u want to save topo file to archive if it is an url
                topo_file = None
        else:
            topo_file = None

        if config.option.test_input_file:
            test_input_file = os.path.abspath(config.option.test_input_file)
            test_input_filename = os.path.basename(config.option.test_input_file)
            test_input_file_path = os.path.join(work_dir, test_input_filename)
            copyfile(config.option.test_input_file, test_input_file_path)
            os.chmod(test_input_file_path, 0o775)

        if config.option.tag_file:
            tag_file = os.path.abspath(config.option.tag_file)
            tag_filename = os.path.basename(config.option.tag_file)
            tag_file_path = os.path.join(work_dir, tag_filename)
            copyfile(config.option.tag_file, tag_file_path)
            os.chmod(tag_file_path, 0o775)

        if config.option.selective_test_file:
            selective_test_file = os.path.abspath(config.option.selective_test_file)
            selective_test_filename = os.path.basename(config.option.selective_test_file)
            selective_test_file_path = os.path.join(work_dir, selective_test_filename)
            copyfile(config.option.selective_test_file, selective_test_file_path)
            os.chmod(selective_test_file_path, 0o775)

        #Copy script-args file or dict (converted to file) if given on cmd line
        #to work_dir, if script-args is not given, config.option.script_args  is set to
        # "{'__nothing__': None}"
        if config.option.script_args:
            if not config.option.script_args == "{'__nothing__': None}":
                temp_arg = config.option.script_args
                script_args_filename = os.path.basename(config.option.script_args)
                if os.path.exists(temp_arg):
                    script_args_path = os.path.join(work_dir, script_args_filename)
                    copyfile(config.option.script_args, script_args_path)
                    os.chmod(script_args_path, 0o775)
                #if dict is given, convert that to file and do the copy
                else:
                    with open(os.path.join(os.path.sep, work_dir, "scriptargs"), "w") as f:
                        f.write(temp_arg)

        #Copy junitxml file name to workdir if --junitxml option is provided
        if config.option.xmlpath:
            os.environ['junitxml'] = config.option.xmlpath

        #Set respective environ variables if one of the 2 options mongo-learn or
        #mongo-read are given on cmd line. Both options cannot coexist
        if config.option.mongo_learn and config.option.mongo_read:
            pytest.exit('Both options mongo-learn & mongo-read cannot coexist!')
        elif config.option.mongo_learn:
            os.environ['cafykit_mongo_learn'] = 'True'
        elif config.option.mongo_read:
            os.environ['cafykit_mongo_read'] = 'True'

        if config.option.commit_check:
            CafyLog.commit_check = True

        #Debug Registration Server code

        reg_dict = {}
        if cafykit_debug_enable: #If user wants to enable our cafy's debug
            os.environ['cafykit_debug_enable'] = 'True' # Set this environ variable to be used in session_finish()
            params = {"test_suite":script_name, "test_id":0,
                    "debug_server_name":CafyLog.debug_server}
            test_bed_file = CafyLog.topology_file
            input_file = CafyLog.test_input_file

            files = {'testbed_file': open(test_bed_file, 'rb'),
                    'input_file': open(input_file, 'rb')}


            if CafyLog.debug_server is None: #Ask if we have to consider a default name
                print("debug_server name not provided in topo file")
            else:
                try:
                    url = 'http://{0}:5001/create/'.format(CafyLog.debug_server)
                    log.info("Calling Registration service to register the test execution (url:%s)" %url)
                    response = requests.post(url, files=files, data=params, timeout = 300)
                    if response.status_code == 200:
                        #reg_dict will contain testbed, input, debug files and reg_id
                        reg_dict = response.text # This reg_dict is a string of dict
                        reg_dict = json.loads(reg_dict)
                        registration_id = reg_dict['reg_id']
                        print("Registration ID :%s" %registration_id)
                        log.info("Registration ID: %s" %registration_id)
                        CafyLog.registration_id = registration_id
                        log.title("Start run for registration id: %s" % CafyLog.registration_id)
                        # log.set_registration_id(registration_id=registration_id)
                    else:
                        reg_dict = {}
                        log.info("Registration server returned code %d " % response.status_code)
                except:
                        log.error("Http call to registration service url:%s is not successful" % url)
        else:
            reg_dict = {}

        config._email = EmailReport(email_list,
                                    email_from,
                                    email_from_passwd,
                                    smtp_server,
                                    smtp_port,
                                    no_email,
                                    topo_file,
                                    script_list, reg_dict)
        config.pluginmanager.register(config._email)

        #Write all.log path to terminal
        reporter = TerminalReporter(config, sys.stdout)
        #reporter.write_line("all.log location: %s" %CafyLog.work_dir)
        reporter.write_line("Complete Log Location: %s/all.log" %CafyLog.work_dir)
        reporter.write_line("Registration Id: %s" % CafyLog.registration_id)


def pytest_unconfigure(config):
    email = getattr(config, '_email', None)
    if email:
        del config._email
        config.pluginmanager.unregister(email)
    # removed the env set by this plugins
    arc_dir = 'ARCHIVE_DIR'
    if os.environ.get(arc_dir):
        #print ('removing env: ARCHIVE_DIR')
        os.environ[arc_dir] = ''
    try:
        # Copy all environment variables into a env.txt named file and
        # save it in work_dir
        tmp_text = dict(os.environ)
        tmp_str_text = str(tmp_text)
        with open(os.path.join(CafyLog.work_dir, "env.txt"), "w") as f:
            f.write(tmp_str_text)
    except:
        pass




def pytest_generate_tests(metafunc):

    """
    count = metafunc.config.option.count
    if hasattr(metafunc.function, 'repeat'):
        mark = metafunc.function.repeat
        if len(mark.args) > 0 and isinstance(mark.args[0], int):
            count = metafunc.function.repeat.args[0]
    if count > 1:
        def make_progress_id(i, n=count):
            return '{0}/{1}'.format(i + 1, n)
        metafunc.parametrize(
            '__pytest_repeat_step_number',
            range(count),
            indirect=True,
            ids=make_progress_id,
        )
    """
    if metafunc.config.option.selective_test_file:
        with open(metafunc.config.option.selective_test_file, 'r') as f:
            content = f.readlines()
            module_name = [x.split('::')[0] for x in content]
            selected_nodeids = [x.rsplit('::', 1)[-1] for x in content]
            module_name = [os.path.relpath(x, str(metafunc.config.rootdir)) for x in module_name]
            #sequence = list(zip(module_name, selected_nodeids))
            #selected_nodeids = ['::'.join(tup) for tup in sequence]
            # remove whitespace characters like `\n` at the end of each line
            selected_nodeids = [x.rstrip('\n') for x in selected_nodeids]
            nodeid_count_dict = {}
            for nodeid in selected_nodeids:
                temp_lst = nodeid.split(',')
                if len(temp_lst) == 2:
                    nodeid_count_dict[temp_lst[0]] = int(temp_lst[1])

        def make_progress_id(i, n):
            return '{0}/{1}'.format(i + 1, n)

        metafunc.fixturenames.append('tmp_ct')
        if nodeid_count_dict:
            if metafunc.function.__name__ in nodeid_count_dict:
                def make_progress_id(i, n=nodeid_count_dict[metafunc.function.__name__]):
                    return '{0}of{1}'.format(i + 1, n)
                metafunc.parametrize('tmp_ct',range(nodeid_count_dict[metafunc.function.__name__]), ids=make_progress_id)
            else:
                print("{0} not found in {1}".format(metafunc.function.__name__,nodeid_count_dict ))
        metafunc.fixturenames.remove('tmp_ct')

def pytest_collection_modifyitems(session, config, items):
    log = CafyLog("cafy")
    if config.option.selective_test_file:
        with open(config.option.selective_test_file, 'r') as f:
            content = f.readlines()
            content = [x.split(',')[0] for x in content]
            module_name =  [x.split('::')[0] for x in content]
            selected_nodeids = [x.split('::',1)[-1] for x in content]
            module_name = [os.path.relpath(x, str(config.rootdir)) for x in module_name]
            sequence = list(zip(module_name, selected_nodeids ))
            selected_nodeids = ['::'.join(tup) for tup in sequence]
            # remove whitespace characters like `\n` at the end of each line
            selected_nodeids = [x.rstrip('\n') for x in selected_nodeids]
        #Modify the items list by picking only those whose nodeid exists in selected_nodeids
        nodeid_pattern = re.compile(r'((?:[\w-]+\/)*[\w-]+\.[\w-]*\:\:[\w-]+\:?\:?\(?\)?\:?\:?[\w-]*)(\[[\w-]+\])?')
        try:
            items[:] = [item for item in items if nodeid_pattern.match(item.nodeid).group(1) in selected_nodeids]
        except:
            log.debug("selected_nodeids = ", selected_nodeids)
            log.error("Error while picking selective testcases")
    if items:
        CafyLog.first_test = items[0]
    else:
        CafyLog.first_test = None

    if config.option.enable_live_update:
        log.info("Live logging the status of testcases enabled.")
        os.environ['enable_live_update'] = 'True'
        #Send the registration_id to CAFY_API_HOST for live logging
        CAFY_API_HOST = os.environ.get('CAFY_API_HOST')
        CAFY_RUN_ID = os.environ.get('CAFY_RUN_ID')
        CAFY_API_KEY = os.environ.get('CAFY_API_KEY')
        log.info("CAFY_API_HOST:{0}, CAFY_RUN_ID:{1},  CAFY_API_KEY:{2}".format(CAFY_API_HOST, CAFY_RUN_ID, CAFY_API_KEY))
        headers = {'Content-Type': 'application/json',
                   'Authorization': 'Bearer {}'.format(os.environ.get('CAFY_API_KEY'))}
        try:
            if CafyLog.registration_id:
                url = '{0}/api/runs/{1}'.format(os.environ.get('CAFY_API_HOST'), os.environ.get('CAFY_RUN_ID'))
                log.info("url: {}".format(url))
                log.info("Calling API service for live logging of reg_id ")
                params = {"reg_id": CafyLog.registration_id}
                response = requests.patch(url, json=params, headers=headers, timeout=120)
                if response.status_code == 200:
                    log.info("Calling API service for live logging of reg_id successful")
                else:
                    log.warning("Calling API service for live logging of reg_id failed")
            else:
                log.warning("registration_id is not set, therefore not sending it to API service for live logging")
        except Exception as e:
            log.warning("Error while sending the reg_id to live logging's api server: {}".format(e))

        #Send the TestCases and its status(upcoming) collected to http://cafy3-dev-lnx:3100 for live logging
        try:
            for item in items:
                if not item.get_marker('Future'):  #Exclude the Future marked testcases to be shown as upcoming
                    nodeid = item.nodeid.split('::()::')
                    finer_nodeid = nodeid[0].split('::')
                    class_name = finer_nodeid[-1]
                    d = dict()
                    d["case_name"] = '.'.join([class_name, item.name]) # To get the testcase_name in format of className.functionName as per allure xml
                    d["status"] = "upcoming"
                    CafyLog.collected_testcases.append(d)
            url = '{0}/api/runs/{1}/cases'.format(os.environ.get('CAFY_API_HOST'), os.environ.get('CAFY_RUN_ID'))
            log.info("url: {}".format(url))
            log.info("Calling API service for live logging of collected testcases ")
            response = requests.post(url, json=CafyLog.collected_testcases, headers=headers, timeout=120)
            if response.status_code == 200:
                log.info("Calling API service for live logging of collected testcases successful")
            else:
                log.warning("Calling API service for live logging of collected testcases failed")

        except Exception as e:
            log.warning("Error while sending the live status of testcases collected: {}".format(e))



def get_datentime():
    '''return date and time as string'''
    _time = time.time()
    return datetime.fromtimestamp(_time).strftime('%Y%m%d-%H%M%S')


def _setup_archive_env():
    '''setup archive env'''
    #print ('setting up env: ARCHIVE_DIR ')
    # create archive folder with 777 permision
    if not os.path.exists(CafyLog.work_dir):
        os.makedirs(CafyLog.work_dir, 0o777)
    else:
        pass
        #print ('{} is already created'.format(CafyLog.work_dir))
    # setup environment variable for cafy user to add files in archive
    os.environ['ARCHIVE_DIR'] = CafyLog.work_dir

def _setup_env():
    '''setup environment'''
    _setup_archive_env()


class EmailReport(object):

    '''
    Email report
    '''
    USER = getpass.getuser()
    CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))
    CAFY_REPO = os.getenv("CAFY_REPO", None)
    # CAFY_REPO will be used for all cafy related logics
    START = datetime.now()
    START_TIME = time.asctime(time.localtime(START.timestamp()))

    def __init__(self, email_addr_list, email_from, email_from_passwd,
                 smtp_server, smtp_port, no_email, topo_file, script_list, reg_dict):
        '''
        @param email_addr_list: list of email address to which email needs to
        be sent.
        @param email_from: email address with which the email will be sent
        @param email_from_passwd: password of email_from email id
        @param smtp_server: smtp server
        @param smtp_port: smtp_port
        @param no_email: if True no email will be sent
        @param script_list: list of script/dir under execution which is
                            (option.file_or_dir)
        @type email_addr_list:  list
        @type email_from: str
        @type email_from_passwd: str
        @type smtp_server: str
        @type smtp_port: int
        @type no_email: bool
        @type script_listL list
        @param reg_dict : registration_dict for debug containing testbed file, input file,
                            debug file and reg_id
        '''
        self.email_addr_list = email_addr_list
        self.email_from = email_from
        self.email_from_passwd = email_from_passwd
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.no_email = no_email
        self.script_list = script_list
        self.topo_file = topo_file
        self.reg_dict = reg_dict
        self.log = CafyLog("cafy")
        self.rclog = CafyLog("debug-rc")
        self.errored_testcase_count = {}
        self.analyzer_testcase = {}
        # using the first item of the script list for archive name as in most
        # cases it would be list with one element because we usally run pyest
        # with single test script
        _current_time = get_datentime()
        email_report = 'email_report.html'
        if self.CAFY_REPO:
            #self.archive_name = CafyLog.work_dir + '.zip'
            #self.archive = os.path.join(CafyLog.work_dir, self.archive_name)
            self.archive = CafyLog.work_dir
            self.email_report = os.path.join(CafyLog.work_dir,
                                             email_report)
        else:
            self.work_dir = None
            self.archive_name = None
            self.archive = None
            self.email_report = email_report

        # Testcase name and its status dict
        self.testcase_dict = OrderedDict()
        self.testcase_time = defaultdict(
            lambda : {'start_time': None, 'end_time': None})
        self.testcase_failtrace_dict = OrderedDict()

    def _sendemail(self):
        print("\n\nSending Summary Email to %s" % self.email_addr_list)
        msg = MIMEMultipart()
        # fixme: add exception handling
        with open(self.email_report) as email_fd:
            # create a text/plain message
            part = MIMEText(email_fd.read(), 'html')
            part['Content-Disposition'] = "inline"
            msg.attach(part)

        msg['Subject'] = ("Cafy Report @%s" % CafyLog.work_dir)
        msg['From'] = self.email_from
        mail_to = COMMASPACE.join(self.email_addr_list)
        msg['To'] = mail_to
        msg.add_header('Content-Type', 'text/html')
        # fixme: add an option to read config from file rather then CLI
        with smtplib.SMTP(self.smtp_server, self.smtp_port,timeout=60) as mail_server:
            if self.email_from_passwd:
                mail_server.ehlo()
                mail_server.starttls()
                mail_server.ehlo()
                mail_server.login(self.email_from, self.email_from_passwd)
            mail_server.send_message(msg)

    def _generate_with_template(self, terminalreporter):
        '''generate report using template'''
        cafy_kwargs = {'terminalreporter': terminalreporter,
                       'testcase_dict': self.testcase_dict,
                       'testcase_failtrace_dict':self.testcase_failtrace_dict,
                       'archive': self.archive,
                       'topo_file': self.topo_file}
        report = CafyReportData(**cafy_kwargs)
        template_file = os.path.join(self.CURRENT_DIR,
                                     "resources/mail_template.html")
        css_file = os.path.join(self.CURRENT_DIR,
                                "resources/cafy_report.css")
        with open(template_file) as html_src, open(css_file) as css_src:
            html_template = html_src.read()
            styles = css_src.read()
        template = Template(html_template)
        cafy_report_rendered = template.render(report=report,
                                               styles=styles)
        return cafy_report_rendered

    def _generate_email_report(self, terminalreporter):
        '''generate email report'''
        with open(self.email_report, 'w') as email_fd:
            email_fd.write(self._generate_with_template(terminalreporter))

    def _copy_files_to_archives(self, option):
        '''copy files to work archive folder'''
        # copy running script(s)/Directory
        file_or_dir_list = option.file_or_dir
        for file_or_dir in file_or_dir_list:
            src = file_or_dir
            if os.path.isdir(src):
                dst = os.path.join(CafyLog.work_dir, os.path.basename(src))
                shutil.copytree(src, dst)
            else:
                dst = CafyLog.work_dir
                shutil.copy2(src, dst)

    def _zip_it(self):
        '''zip everything under work_dir'''
        cwd = os.getcwd()
        os.chdir(CafyLog.work_dir)
        with zipfile.ZipFile(self.archive_name, 'w') as arc_zip:
            for file_or_dir in os.listdir(CafyLog.work_dir):
                if file_or_dir == self.archive_name:
                    continue
                else:
                    arc_zip.write(file_or_dir)
        os.chdir(cwd)

    def _create_archive(self, option):
        '''generate archive'''
        self._copy_files_to_archives(option)
        self._zip_it()
        print("Run archive is located at: %s" % CafyLog.work_dir)

    def get_test_name(self,name):
        report_name = name.replace("::()::", ".")
        report_name = report_name.split('::')[-1]
        return report_name

    def get_open_files(self, pid):
        """
        Find files opened by specified process ID(s).
        Parameters
        ----------
        pids : list of int Process IDs.
        Returns
        -------
        files : list of str Open file names.
        """
        try:
            cmd = ['/usr/sbin/lsof', '-p', str(pid)]
            fd_out = subprocess.check_output(cmd)
            fd_out = str(fd_out).split("\\n")
            return fd_out
        except Exception:
            pass

    def get_open_files_of_pid_count(self, pid):
        """
        Find files opened by specified process ID(s).
        Parameters
        ----------
        pids :  Process IDs
        Returns: count
        """
        try:
            ps = subprocess.Popen(('lsof', '-p', str(pid)), stdout=subprocess.PIPE)
            fd_wc = subprocess.check_output(('wc'), stdin=ps.stdout)
            return str(fd_wc)
        except Exception:
            pass

    def initiate_analyzer(self, reg_id, test_case, debug_server):
        headers = {'content-type': 'application/json'}

        params = {"test_case": test_case,
                  "reg_id": reg_id,
                  "debug_server_name": debug_server}
        if CafyLog.debug_server is None:
            self.log.info("debug_server name not provided in topo file")
        else:
            try:
                url = "http://{0}:5001/initiate_analyzer/".format(CafyLog.debug_server)
                self.log.info("Calling registration service (url:%s) to initialize analyzer" % url)
                response = requests.post(url, data=params, timeout=300)
                if response.status_code == 200:
                    self.log.info("Analyzer initialized")
                    return True
                else:
                    self.log.error("Analyzer failed %d" % response.status_code)
                    return False
            except:
                self.log.error("Http call to registration service url:%s is not successful" % url)
                return False

    def pytest_runtest_setup(self, item):
        test_case = self.get_test_name(item.nodeid)
        self.log.set_testcase(test_case)
        if item == CafyLog.first_test and self.reg_dict:
            reg_id = self.reg_dict['reg_id']
            debug_server = CafyLog.debug_server
            self.initiate_analyzer(reg_id, test_case, debug_server)

    def pytest_runtest_teardown(self, item, nextitem):
        if nextitem is None:
            self.log.set_testcase("Teardown")
        else:
            testcase_name = self.get_test_name(nextitem.nodeid)
            # self.log.set_testcase(testcase_name)
        testcase_name = self.get_test_name(item.nodeid)
        self.log.info('Teardown module for testcase {}'.format(testcase_name))

    @pytest.fixture(scope='function', autouse=True)
    def check_test_run(self, request):
        '''
        All the testcases will check if the CafyLog._triggerFlags list is non empty and if yes,
        check if the testcase is marked with a autofail marker that is present in the above list and if yes,
        raise an exception
        :param request:
        :return:
        '''
        marker = request.node.get_marker('autofail')  # Is always None
        if not marker:
            return
        if bool(marker):
            for arg in marker.args:
                if request.node.parent.obj.has_autofail_trigger(arg):

                    raise CafyException.AutoFailMarkerException("Failing this testcase automatically as this has triggered condition %s from %s()" \
                                                                %(arg, CafyLog._triggerFlags[arg]))
                    #pytest.fail("Failing this testcase automatically as this has triggered condition %s" % arg)

    def post_testcase_status(self, reg_id, test_case, debug_server):
        analyzer_status = False
        headers = {'content-type': 'application/json'}

        params = {"test_case": test_case,
                  "reg_id": reg_id,
                  "debug_server_name": debug_server}

        try:
            analyzer_status = self.check_analyzer_status(params, headers)
            if not analyzer_status:
                self.log.info("Analyzer still working, Continuing Test case")
        except Exception as err:
            self.log.error("Exception hit while checking analyzer status {}".format(repr(err)))
            self.log.error("Analysis Failed exiting check")
            analyzer_status = False

        return analyzer_status

    def check_analyzer_status(self, params, headers):
        if CafyLog.debug_server is None:
            self.log.info("debug_server name not provided in topo file")
        else:
            try:
                url = "http://{0}:5001/end_test_case/".format(CafyLog.debug_server)
                self.log.info("Calling registration service (url:%s) to check analyzer status" % url)
                response = requests.get(url, data=params, timeout=60)
                if response.status_code == 200:
                    return response.json()['analyzer_status']
                else:
                    self.log.error("Analyzer status check failed %d" % response.status_code)
                    raise CafyException.CafyBaseException("Analyzer is failing")
            except:
                self.log.error("Http call to registration service url:%s is not successful" % url)
                raise CafyException.CafyBaseException("Analyzer is failing")



    # pytest.hookimpl(tryfirst=True)
    def pytest_runtest_logreport(self, report):

        testcase_name =  self.get_test_name(report.nodeid)
        if report.when == 'setup':
            self.log.set_testcase(testcase_name)
            self.log.title("Start test:  %s" %(testcase_name))
            self.testcase_time[testcase_name]['start_time'] = datetime.utcnow()
            #Notify testcase_name to handshake server
            #If config.debug_enable is False, the reg_dict is empty, So u want to skip talking to handshake server
            if self.reg_dict:
                params = {"testcase_name": testcase_name}
                headers = {'content-type': 'application/json'}
                if CafyLog.debug_server is None:
                    print("debug_server name not provided in topo file")
                    self.log.error("debug_server name not provided in topo file")
                else:
                    try:
                        url = 'http://{0}:5001/registertest/'.format(CafyLog.debug_server)
                        self.log.info("Calling registration service to start handshake(url:%s" % url)
                        response = requests.post(url, json=params, headers=headers, timeout=300)
                        if response.status_code == 200:
                            self.log.info("Handshake part of registration service was successful")
                        else:
                            self.log.error("Handshake part of registration server returned code %d " % response.status_code)
                    except:
                        self.log.error("Http call to registration service url:%s is not successful" % url)



        if report.when == 'teardown':
            status = "unknown"
            if testcase_name in self.testcase_dict:
                status = self.testcase_dict[testcase_name]
            try:
                temp_json ={}
                temp_json["name"] = testcase_name
                temp_json["action"]= self.log.device_actions
                temp_json['testcase_status'] = status
                if status != "passed" :
                    temp_json['error'] = CafyLog.fail_log_msg
                    temp_json["exception"] = self.log.exception_details
                    temp_json["analyzer_exceptions"] = self.log.analyzer_exceptions
                    self.log.analyzer_exceptions = None
                self.log.buffer_to_retest.append(temp_json)
            except Exception as err:
                self.log.info("Error {} happened while getting deta for retest" .format(err))

            create_fd_file = os.environ.get('enable_fd_collection', False)
            if create_fd_file:
                self.log.info("File descriptor collection enabled and it will be saved in file_descriptors.txt in the archive")
                pid = os.getpid()
                fd_count = self.get_open_files_of_pid_count(pid)

                fd_list = self.get_open_files(pid)
                try:
                    with open(os.path.join(os.path.sep, CafyLog.work_dir, "file_descriptors.txt"), "a") as f:
                        f.write("\n")
                        f.write("Testcase_name : " +CafyLog.testcase_name)
                        f.write("\n")
                        if fd_count:
                            f.write("Count : %s" %fd_count)
                        f.write("\n")
                        f.write("_ _ _ _ _ "*15)
                        f.write("\n")
                        if fd_list:
                            for line in fd_list:
                                f.write(line + '\n')
                        f.write("\n")
                        f.write("==========" * 15)
                except Exception:
                    pass

            if os.environ.get('enable_live_update'):
                # Send the testcasename and its status along with failtrace if any to the live logging API service
                headers = {'Content-Type': 'application/json',
                                   'Authorization': 'Bearer {}'.format(os.environ.get('CAFY_API_KEY'))}
                try:
                    for item in CafyLog.collected_testcases:
                        if testcase_name in item.values():
                            item['status'] = self.testcase_dict[testcase_name]
                            item['start_time'] = self.testcase_time[testcase_name]['start_time'].isoformat()
                            item['end_time'] = self.testcase_time[testcase_name]['end_time'].isoformat()
                            if testcase_name in self.testcase_failtrace_dict:
                                item['fail_log'] = CafyLog.fail_log_msg
                    url = '{0}/api/runs/{1}/cases'.format(os.environ.get('CAFY_API_HOST'),
                                                                 os.environ.get('CAFY_RUN_ID'))
                    #self.log.info("url: {}".format(url))
                    #self.log.info("Calling API service for live logging of executed testcases ")
                    #self.log.info("json = {0}".format(CafyLog.collected_testcases))
                    response = requests.post(url, json=CafyLog.collected_testcases, headers=headers)
                    if response.status_code == 200:
                        self.log.info("Calling API service for live logging of executed testcase successful")
                    else:
                        self.log.warning("Calling API service for live logging of executed testcases failed")

                except Exception as e:
                    self.log.warning("Error while sending the live status of executed testcases: {}".format(e))


            self.log.title("Finish test: %s (%s)" %(testcase_name,status))
            self.log.info("="*80)

        #The following if block is executed for @pytest.mark.xfail(run=False) and
        #@@pytest.mark.skip(..) markers because testcases marked with these
        #will never go into call stage
        if report.when == 'setup' and report.outcome == 'skipped':
            if hasattr(report, "wasxfail"):
                #This is to handle tests that are marked with @pytest.mark.xfail(run=False)
                #which means don't execute the testcase. Such testcase will never go into the
                #report.when=call stage
                testcase_name = self.get_test_name(report.nodeid)
                self.testcase_dict[testcase_name] = 'xfailed'

            else:
                #This is to handle tests that are marked with @pytest.mark.skip(..)
                #which means skip the testcase. Such testcase will never go into the
                #report.when=call stage
                testcase_name = self.get_test_name(report.nodeid)
                self.testcase_dict[testcase_name] = 'skipped'
            self.testcase_time[testcase_name]['end_time'] = datetime.utcnow()
            '''
            if report.longrepr:
                self.testcase_failtrace_dict[testcase_name] = report.longrepr
            else:
                self.testcase_failtrace_dict[testcase_name] = None
            '''
        elif report.when == 'call':
            testcase_name = self.get_test_name(report.nodeid)
            if hasattr(report, "wasxfail"):
                if report.skipped:
                    testcase_status = "xfailed"
                elif report.passed:
                    testcase_status = "xpassed"
                else:
                    testcase_status = report.outcome

                self.testcase_dict[testcase_name] = testcase_status
                self.testcase_time[testcase_name]['end_time'] = datetime.utcnow()
                if testcase_status == 'failed':
                    self.testcase_failtrace_dict[testcase_name] = CafyLog.fail_log_msg
                    #print('failmsg = ', self.testcase_failtrace_dict[testcase_name])
                    #
                '''
                if report.longrepr:
                    self.testcase_failtrace_dict[testcase_name] = report.longrepr
                else:
                    self.testcase_failtrace_dict[testcase_name] = None
                '''
            else:
                testcase_status = report.outcome
                self.testcase_dict[testcase_name] = testcase_status
                self.testcase_time[testcase_name]['end_time'] = datetime.utcnow()
                if testcase_status == 'failed':
                    if report.longrepr:
                        self.testcase_failtrace_dict[testcase_name] = report.longrepr
                    else:
                        self.testcase_failtrace_dict[testcase_name] = None

        # Add the testcase status to testcase_dict as error if the test failed in setup
        try:
            if report.when == 'setup' and report.outcome == 'failed':
                testcase_name = self.get_test_name(report.nodeid)
                self.testcase_dict[testcase_name] = 'error'
                self.testcase_time[testcase_name]['end_time'] = datetime.utcnow()
        except Exception as e:
            self.log.error("Error getting the testcase status for setup failure: {}".format(e))


    @pytest.hookimpl(hookwrapper=True, trylast=True)
    def pytest_runtest_makereport(self, item, call):
        outcome = (yield)
        if call.when =='call':
            report = outcome.get_result()
            testcase_name = self.get_test_name(report.nodeid)
            if self.reg_dict:
                reg_id = self.reg_dict.get('reg_id')
                test_class = report.nodeid.split('::')[1]
                analyzer_status = False
                try:
                    if (test_class not in self.analyzer_testcase.keys()) or self.analyzer_testcase.get(test_class) == 1:
                        analyzer_status = self.post_testcase_status(reg_id, testcase_name, CafyLog.debug_server)
                        self.log.info('Analyzer Status is {}'.format(analyzer_status))
                    else:
                        self.log.info('Analyzer is not invoked as testcase failed in setup')
                    if isinstance(analyzer_status, bool):
                        return
                    failures = json.loads(analyzer_status.get('failures',[]))
                    if len(failures):
                        self.log.analyzer_exceptions = failures
                        errmsg = 'Test case failed due to crash/traceback {}'.format(pformat(failures))
                        if CafyLog.fail_log_msg == None:
                            CafyLog.fail_log_msg = errmsg
                        if report.outcome != 'failed':
                            self.log.info("Invoking collector for analyzer failures")
                            self._call_collector_on_analyzer_based_failure(item)
                        self.log.error(errmsg)
                        test_outcome = 'failed'
                        report = TestReport(
                            report.nodeid,
                            report.location,
                            report.keywords,
                            test_outcome,
                            report.longrepr,
                            report.when,
                            report.sections,
                            report.duration,
                        )
                        outcome.force_result(report)
                except:
                    self.log.error('Error while handling analyzer status')

    def _get_test_details(self, node):
        inherited_classes = []
        base_classes = inspect.getmro(node.cls)
        for base_class in base_classes:
            if base_class.__name__ not in ["ApBase", "object"]:
                inherited_classes.append(base_class.__name__)
        index = 1
        if len(base_classes) == 3:
            index = 0
        base_class_name = base_classes[index].__name__
        testcase_name = node.name
        return (testcase_name, base_class_name, inherited_classes)

    def _call_collector_on_analyzer_based_failure(self, node):

        testcase_name, base_class_name, inherited_classes = self._get_test_details(node)
        failed_attr = list()
        exception_name = "AnalyzerError"
        collector_exception_name_list = [exception_name]
        collector_actual_obj_dict_list = [None]
        collector_actual_obj_name_list = [None]
        collector_failed_attribute_list = [failed_attr]

        headers = {'content-type': 'application/json'}
        params = {"testcase_name": testcase_name, "class_name": base_class_name,
                  "inherited_classes": inherited_classes,
                  "reg_dict": self.reg_dict, "actual_obj_name": collector_actual_obj_name_list,
                  "actual_obj_dict": collector_actual_obj_dict_list,
                  "failed_attr": collector_failed_attribute_list,
                  "debug_server_name": CafyLog.debug_server,
                  "exception_name": collector_exception_name_list}
        response = self.invoke_reg_on_failed_testcase(params, headers)
        if response is not None and response.status_code == 200:
            if response.text:
                self.log.info("Debug Collector logs: %s" % response.text)


    def check_call_report(self, item, nextitem):
        """
        If test method in a testclass fails then mark the rest of the test methods
        in that as 'skipped'
        """
        reports = runtestprotocol(item, nextitem=nextitem)
        for report in reports:
            if report.when == "call":
                if report.outcome == "failed":
                    if 'insta-stop' in CafyLog.script_args:
                        #Get the list or value of insta-stop key passed to script-args
                        #on cmd line
                        insta_stop_methods = CafyLog.script_args['insta-stop']
                        #Get the class name of the method
                        class_name = item.cls
                        base_classes = inspect.getmro(class_name)
                        base_class_name = base_classes[0].__name__
                        #Make a string as class_name.method_name
                        method_with_class_name = base_class_name+'.'+item.name
                        if method_with_class_name in insta_stop_methods:
                            for test_method in item.parent._collected[item.parent._collected.index(item):]:
                                test_method.add_marker(pytest.mark.skipif("True"))
                break

    def pytest_runtest_protocol(self, item, nextitem):
        # add to the hook
        item.ihook.pytest_runtest_logstart(
            nodeid=item.nodeid, location=item.location,
        )
        self.check_call_report(item, nextitem)
        return True

    def pytest_exception_interact(self, node, call, report):
        if report.failed:
            CafyLog().fail(str(call.excinfo))
            if report.outcome == 'failed':
                #If config.debug_enable is False, the reg_dict is empty, So u want to skip talking to collector server
                if self.reg_dict:
                    if hasattr(report, 'when'):
                        if report.when == 'setup':
                            test_class = node.nodeid.split('::')[1]
                            if test_class not in self.analyzer_testcase.keys():
                                self.analyzer_testcase.update({test_class: 1})
                            else:
                                self.analyzer_testcase[test_class] += 1
                            if node.cls not in self.errored_testcase_count:
                                self.errored_testcase_count[node.cls] = 1
                            else:
                                self.errored_testcase_count[node.cls]+=1

                        if (node.cls in self.errored_testcase_count and self.errored_testcase_count[node.cls]==1) or report.when!='setup':
                            testcase_name = node.name
                            inherited_classes = []
                            if node.cls:
                                testcase_name, base_class_name, inherited_classes = self._get_test_details(node)
                            else:
                                base_class_name = None

                            exception_type = call.excinfo.type
                            try:
                                if issubclass(exception_type, CafyException.CafyBaseException):
                                    exception_details = call.excinfo.value.get_exception_details()
                                    self.log.exception_details = exception_details
                            except:
                                self.log.info("Error happened while getting exception details for retest")

                            # Check if the exception encountered is not an instance of CafyBaseException, then don't invoke collector service
                            if not issubclass(exception_type, CafyException.CafyBaseException):
                                self.log.info(
                                    "The encountered exception '%s' is not an instance of CafyBaseException, It could be a python built-in exception."
                                    " Therefore collector service will not be invoked " \
                                    % exception_type.__name__)

                            else:
                                collector_exception_name_list = []
                                collector_actual_obj_dict_list = []
                                collector_actual_obj_name_list = []
                                collector_failed_attribute_list = []
                                rc_exception_name_list = []
                                rc_actual_obj_dict_list = []
                                rc_actual_obj_name_list = []
                                rc_failed_attribute_list = []

                                exception_name = exception_type.__name__
                                if exception_name == "CompositeError":
                                    for curr_exception in call.excinfo.value.exceptions:
                                        exception_type = type(curr_exception).__name__
                                        call_dict = {}
                                        if 'VerificationError' in exception_type:
                                            exception_name = 'VerificationError'
                                            if hasattr(curr_exception, 'verifier'):
                                                call_dict['verifier'] = curr_exception.verifier
                                            if hasattr(curr_exception, 'columns'):
                                                call_dict['columns'] = curr_exception.columns
                                        elif 'TgenCheckTrafficError'in exception_type:
                                            exception_name = 'TgenCheckTrafficError'
                                            if hasattr(curr_exception, 'item_stats'):
                                                call_dict['item_stats'] = curr_exception.item_stats
                                            if hasattr(curr_exception, 'flow_stats'):
                                                call_dict['flow_stats'] = curr_exception.flow_stats
                                        else:
                                            exception_name = 'None'

                                        self.handle_all_exceptions(base_class_name, call_dict, exception_name,
                                                                   collector_exception_name_list, collector_actual_obj_dict_list,
                                                                   collector_actual_obj_name_list, collector_failed_attribute_list,
                                                                   rc_exception_name_list, rc_actual_obj_dict_list,
                                                                   rc_actual_obj_name_list,
                                                                   rc_failed_attribute_list)
                                else:
                                    call_dict = call.excinfo.value.__dict__
                                    self.handle_all_exceptions(base_class_name, call_dict, exception_name,
                                                               collector_exception_name_list, collector_actual_obj_dict_list,
                                                               collector_actual_obj_name_list, collector_failed_attribute_list,
                                                               rc_exception_name_list, rc_actual_obj_dict_list,
                                                               rc_actual_obj_name_list,
                                                               rc_failed_attribute_list)

                                headers = {'content-type': 'application/json'}

                                if len(collector_actual_obj_dict_list) > 0:
                                    params = {"testcase_name": testcase_name, "class_name": base_class_name,
                                              "inherited_classes": inherited_classes,
                                              "reg_dict": self.reg_dict, "actual_obj_name": collector_actual_obj_name_list,
                                              "actual_obj_dict": collector_actual_obj_dict_list,
                                              "failed_attr": collector_failed_attribute_list,
                                              "debug_server_name": CafyLog.debug_server,
                                              "exception_name": collector_exception_name_list}
                                    response = self.invoke_reg_on_failed_testcase(params, headers)
                                    if response is not None and response.status_code == 200:
                                        if response.text:
                                            self.log.info("Debug Collector logs: %s" % response.text)

                                if len(rc_actual_obj_dict_list) > 0:
                                    params = {"testcase_name": testcase_name, "class_name": base_class_name,
                                              "inherited_classes": inherited_classes,
                                              "reg_dict": self.reg_dict, "actual_obj_name": rc_actual_obj_name_list,
                                              "actual_obj_dict": rc_actual_obj_dict_list, "failed_attr": rc_failed_attribute_list,
                                              "debug_server_name": CafyLog.debug_server,
                                              "exception_name": rc_exception_name_list}
                                    response = self.invoke_rc_on_failed_testcase(params, headers)
                                    if response is not None and response.status_code == 200:
                                        if response.json().get("traffic_logs"):
                                            self.rclog.info("Debug RC logs: \n%s" % response.json()["traffic_logs"])
                    else:
                        self.log.debug("Type of report obtained is %s. Debug engine is only triggered for reports of type TestReport" %type(report))

    def handle_all_exceptions(self, base_class_name, call_dict, exception_name,
                              collector_exception_name_list,
                              collector_actual_obj_dict_list,
                              collector_actual_obj_name_list,
                              collector_failed_attribute_list,
                              rc_exception_name_list,
                              rc_actual_obj_dict_list,
                              rc_actual_obj_name_list,
                              rc_failed_attribute_list):
        failed_attr = []
        if (exception_name == "VerificationError") and \
                bool(call_dict):
            actual_obj_name = None
            actual_obj_dict = {}
            failed_attr = []
            if 'verifier' in call_dict:
                actual_obj = call_dict['verifier']
                actual_obj_name = actual_obj.__class__.__qualname__
                blacklist_keys = ['log',
                                  '__compared_to__']  # We dont want to pass these keys and thie values because they r not json serializable
                actual_obj_dict = {}
                for key, val in actual_obj.__dict__.items():
                    if key not in blacklist_keys:
                        actual_obj_dict[key] = val
                if 'columns' in call_dict:
                    failed_attr = call_dict['columns']
                else:
                    self.log.error("'columns' key not found in %s" %call_dict)

                # Verification errors are sent to Collector, so add to
                # the collector list to be used for collection service
                collector_actual_obj_dict_list.append(actual_obj_dict)
                collector_actual_obj_name_list.append(actual_obj_name)
                collector_failed_attribute_list.append(failed_attr)
                collector_exception_name_list.append(exception_name)
            else:
                self.log.error("Verification Error encountered , but 'verifier' key not found in %s. "
                               "The absence of 'verifier' key could be due to this exception not being raised from "
                               "verification code. Therefore debug engine's collector  won't be invoked " % call_dict)


        elif (exception_name == "TgenCheckTrafficError") and \
                bool(call_dict):
            #item_stats and flow_stats keys are mandatory in TgenCheckTrafficError exception.
            # If not, it could be a misuse of exception like being raised without a context
            if 'item_stats' in call_dict:
                item_stats = call_dict['item_stats']
                if 'flow_stats' in call_dict:
                    flow_stats = call_dict['flow_stats']

                    failed_attr = ["traffic_error"]
                    actual_obj_dict = {"item_stats": item_stats, "flow_stats": flow_stats}
                    actual_obj_name = "traffic_stats"

                    # Traffic errors are sent to RC Engine, so add to
                    # the RC list to be used for RC Engine service
                    rc_actual_obj_dict_list.append(actual_obj_dict)
                    rc_actual_obj_name_list.append(actual_obj_name)
                    rc_failed_attribute_list.append(failed_attr)
                    rc_exception_name_list.append(exception_name)

                    collector_actual_obj_dict_list.append(None)
                    collector_actual_obj_name_list.append(None)
                    collector_failed_attribute_list.append(None)
                    collector_exception_name_list.append(exception_name)
                else:
                    self.log.error("'flow_stats' key not found in %s. "
                                   "Could be because TgenCheckTrafficError exception is not raised in the context " %call_dict)
            else:
                self.log.error("'item_stats' key not found in %s. "
                               "Could be because TgenCheckTrafficError exception is not raised in the context" % call_dict)

        else:
            # All other errors are sent to Collector, so add to
            # the collector list to be used for collection service
            collector_actual_obj_dict_list.append(None)
            collector_actual_obj_name_list.append(None)
            collector_failed_attribute_list.append(failed_attr)
            collector_exception_name_list.append(exception_name)


    def invoke_reg_on_failed_testcase(self, params, headers):
        if CafyLog.debug_server is None:
            self.log.info("debug_server name not provided in topo file")
        else:
            try:
                url = "http://{0}:5001/startdebug/".format(CafyLog.debug_server)
                self.log.info("Calling registration service (url:%s) to start collecting" % url)
                response = requests.post(url, json=params, headers=headers, timeout=1500)
                if response.status_code == 200:
                    return response
                else:
                    self.log.error("start_debug part of handshake server returned code %d" % response.status_code)
                    return None
            except:
                self.log.error("Http call to registration service url:%s is not successful" %url)
                return None

    def invoke_rc_on_failed_testcase(self, params, headers):
        if CafyLog.debug_server is None:
            self.log.info("debug_server name not provided in topo file")
        else:
            try:
                url = "http://{0}:5001/startrootcause/".format(CafyLog.debug_server)
                self.log.info("Calling RC engine to start rootcause (url:%s)" % url)
                response = requests.post(url, json=params, headers=headers, timeout=600)
                if response.status_code == 200:
                    return response
                else:
                    self.log.error("startrootcause part of RC engine returned code %d" % response.status_code)
                    return None
            except:
                self.log.error("Http call to root cause service url:%s is not successful" % url)
                return None



    def pytest_terminal_summary(self, terminalreporter):
        '''this hook is the execution point of email plugin'''
        self._generate_email_report(terminalreporter)
        self._generate_all_star_log_html()
        self._generate_all_log_html()
        if self.CAFY_REPO:
            option = terminalreporter.config.option
            # self._create_archive(option)
            #If junitxml option is given on cmd line, this file is available
            #only after run is complete
            _junitxml_filename = os.environ.get('junitxml')
            if _junitxml_filename:
                junitxml_filename = os.path.basename(_junitxml_filename)
                junitxml_file_path = os.path.join(CafyLog.work_dir, junitxml_filename)
                #Chec if source and dest are same, then don't copy else copy
                if junitxml_file_path != _junitxml_filename:
                    copyfile(_junitxml_filename, junitxml_file_path)
                    os.chmod(junitxml_file_path, 0o775)

        @wrapt_timeout(600)
        def terminal_summary_timeout(terminalreporter, *args):
            try:
                temp_list = []
                terminalreporter.write_line("\n TestCase Summary Status Table")
                for k,v in self.testcase_dict.items():
                    temp_list.append((k,v))
                self.log.info("Printing the tabulated summary table")
                print (tabulate(temp_list, headers=['Testcase_name', 'Status'], tablefmt='grid'))
                self.log.info("Preparing to send email")
                if not self.no_email:
                    try: 
                        self._sendemail()
                    except Exception as err: 
                        self.log.error("Error when sending email: {err}".format(err=str(err)))
            except TimeoutError as err:
                trace = traceback.format_exc()
                print(trace)
                self.log.error("Encountered timeout of 600s in pytest_terminal_summary()")
                raise err
                
        
        terminal_summary_timeout(terminalreporter)
        #Unset environ variables cafykit_mongo_learn & cafykit_mongo_read if set
        if os.environ.get('cafykit_mongo_learn'):
            del os.environ['cafykit_mongo_learn']
        if os.environ.get('cafykit_mongo_read'):
            del os.environ['cafykit_mongo_read']

    def _parse_all_log(self, input_file_handler):
        log_parsing_state = LogState.NONE
        log_grouping = None
        separator_line = re.compile('-[a-zA-Z]+-+.*> [=]+$')
        start_test_line = re.compile('Start test:\W+(.*)$')
        end_test_line = re.compile('Finish test:\W+(.*)\W\((.*)\)$')
        split_log_line = re.compile('^-+([a-zA-Z]+)-+(.*)$')

        all_log_groupings = []
        for log_line in input_file_handler:
            if separator_line.search(log_line):
                continue
            elif start_test_line.search(log_line):
                # When we encounter start of test case, irrespective of current state we reset to LogState.TESTCASE
                name = start_test_line.search(log_line).group(1)
                log_grouping = TestCase(name=name, description="")
                all_log_groupings.append(log_grouping)
                log_parsing_state = LogState.TESTCASE
            elif end_test_line.search(log_line):
                if log_parsing_state is LogState.TESTCASE:
                    if end_test_line.search(log_line).group(2) == 'failed':
                        log_grouping.failed = True
                    log_parsing_state = LogState.NONE
                else:
                    # raise ValueError('Cannot end a test case from this state')
                    pass
            else:
                if log_parsing_state is LogState.NONE:
                    # print("Starting generic log")
                    log_grouping = GenericLogGrouping()
                    all_log_groupings.append(log_grouping)
                    log_parsing_state = LogState.GENERIC
                processed_log_line = split_log_line.search(log_line)
                if processed_log_line:
                    log_grouping.append_log_line(LogLine(html.escape(processed_log_line.group(2)), processed_log_line.group(1).upper()))
        return all_log_groupings
    
    def _generate_all_star_log_html(self):
        log_file_name = os.path.join(CafyLog.work_dir, "all.log")
        try:
            output_file_name = os.path.join(CafyLog.work_dir, "star.log.html")
            log_update_file = "logupdate.py"
            cmd = "python {log_update_file} {input_file} > {output_file}".format(log_update_file = log_update_file, input_file = log_file_name, output_file = output_file_name)
            subprocess.Popen(cmd, shell=True)
        except FileNotFoundError:
            return

    def _generate_all_log_html(self):
        log_file_name = os.path.join(CafyLog.work_dir, "all.log")
        try:
            input_file_handler = open(log_file_name, 'r')
            all_log_groupings = self._parse_all_log(input_file_handler)
            template_file_name = os.path.join(self.CURRENT_DIR,
                                     "resources/all_log_template.html")
            with open(template_file_name) as html_src:
                html_template = html_src.read()
                template = Template(html_template)
            output_file_name = os.path.join(CafyLog.work_dir, "all.log.html")
            with open(output_file_name, 'w') as output_file:
                output_file.write(template.render(log_groupings = all_log_groupings))
        except FileNotFoundError:
                return

    def _get_analyzer_log(self):
        params = {"reg_id": CafyLog.registration_id,
                  "email_addr_list": self.email_addr_list,
                  "debug_server_name": CafyLog.debug_server}
        url = 'http://{0}:5001/get_analyzer_log/'.format(CafyLog.debug_server)
        try:
            response = requests.get(url, data=params, timeout=300)
            if response is not None and response.status_code == 200:
                if response.text:
                    if 'Content-Disposition' in response.headers:
                        analyzer_log_filename = response.headers['Content-Disposition'].split('filename=')[-1]
                        analyzer_log_file_full_path = os.path.join(CafyLog.work_dir, analyzer_log_filename)
                        with open(analyzer_log_file_full_path, 'w') as f:
                            f.write(response.text)
                            self.log.info('{} saved at {}'.format(analyzer_log_filename, CafyLog.work_dir))
                    else:
                        self.log.info("No analyzer log file received")
        except Exception as err:
            self.log.info('No Analyzer log file receiver')


    @pytest.hookimpl(tryfirst=True)
    def pytest_sessionfinish(self):
        test_data_file = os.path.join(CafyLog.work_dir, "testdata.json")
        self.log.info("Test data generated at %s" % test_data_file)
        CafyLog.TestData.save(test_data_file,overwrite=True)
        debug_enabled_status = os.getenv("cafykit_debug_enable", None)
        if debug_enabled_status and CafyLog.registration_id:
            self.log.title("End run for registration id: %s" % CafyLog.registration_id)
            self._get_analyzer_log()
            params = {"reg_id": CafyLog.registration_id,
                      "topo_file": CafyLog.topology_file,
                      "input_file": CafyLog.test_input_file}
            headers = {'content-type': 'application/json'}
            try:
                url = 'http://{0}:5001/uploadcollectorlogfile/'.format(CafyLog.debug_server)
                print("url = ", url)
                self.log.info("Calling registration upload collector logfile service (url:%s)" %url)
                response = requests.post(url, json=params, headers=headers, timeout=300)
                if response is not None and response.status_code == 200:
                    if response.text:
                        summary_log = response.text
                        if '+'*120 in response.text:
                            summary_log, verbose_log = response.text.split('+'*120)
                        self.log.info ("Debug Collector logs: %s" %(summary_log))
                        if 'Content-Disposition' in response.headers:
                            debug_collector_log_filename = response.headers['Content-Disposition'].split('filename=')[-1]
                            collector_log_file_full_path = os.path.join(CafyLog.work_dir,debug_collector_log_filename)
                            with open(collector_log_file_full_path, 'w') as f:
                                f.write(summary_log)
                            verbose_log_file_path = collector_log_file_full_path.replace("debug_collection.log",
                                                                                         "verbose_collection.log")
                            with open(verbose_log_file_path, 'w') as f:
                                f.write(verbose_log)
                            try:
                                DebugLibrary.convert_collector_logs_to_json(collector_log_file_full_path)
                            except:
                                self.log.info("Failed to convert collector logs to json")
                        else:
                            self.log.info("No collector log file received")

                url = 'http://{0}:5001/deleteuploadedfiles/'.format(CafyLog.debug_server)
                self.log.info("Calling registration delete upload file service (url:%s)" % url)
                response = requests.post(url, json=params, headers=headers, timeout=300)
                if response.status_code == 200:
                    self.log.info("Topology and input files deleted from registration server")
                else:
                    self.log.info("Error in deleting topology and input files from registration server")
            except:
                self.log.info("Error in uploading collector logfile")
            try:
                with open(os.path.join(CafyLog.work_dir, "retest_data.json"), "w") as f:
                    f.write(json.dumps(self.log.buffer_to_retest, indent=4))
            except Exception as error:
                self.log.info(error)
        '''
        line_regex = re.compile(r"\-\w*\-{1,}\-\d{4}\-\d{2}\-\d{2}T\d*\-\d*\-\d*\[([\w\-:]*)\](\[.*\])?>")
        log_filename = os.path.join(CafyLog.work_dir, 'all.log')
        if os.path.exists(log_filename):
            output_filepath = None
            with open(log_filename, "r") as in_file:
                # Open input file in 'read' mode and loop over each log line
                for line in in_file:
                    # If log line matches our regex, print to console, and output file
                    output = line_regex.search(line)
                    if output:
                        if output.group(1) == 'MainThread':
                            pass
                        else:
                            output_filename = "thread_"+ output.group(1) + ".log"
                            output_filepath = os.path.join(CafyLog.work_dir, output_filename)
                            with open(output_filepath, "a") as out_file:
                                print(line)
                                out_file.write(line)
                    else:
                        if output_filepath:
                            with open(output_filepath, "a") as out_file:
                                print(line)
                                out_file.write(line)
        '''

class CafyReportData(object):

    '''cafy email report class'''

    build_info = namedtuple('build_info', ['XR_Workspace', 'XR_EFR',
                                           'Calvados_Workspace',
                                           'Calvados_EFR'])
    testcase = namedtuple('testcase', ['name', 'result', 'fail_log', 'url'])
    summary = namedtuple('summary', ['passed', 'failed', 'not_run', 'total'])

    def __init__(self, terminalreporter, testcase_dict, testcase_failtrace_dict, archive, topo_file):
        self.terminalreporter = terminalreporter
        self.testcase_dict = testcase_dict
        self.testcase_failtrace_dict = testcase_failtrace_dict
        self.start = EmailReport.START
        self.start_time = EmailReport.START_TIME
        # Basic details
        option = self.terminalreporter.config.option
        self.script_list = option.file_or_dir
        self.title = ' '.join(self.script_list)
        self.image = os.getenv("IMAGE", "Unknown")
        if os.environ.get("BUILD_URL"):
            self.jenkins_url = os.environ.get("BUILD_URL") + "console"
        else:
            self.jenkins_url = None
        # Build Info
        self.xr_ws = os.getenv("XRWS", "Unknown")
        self.xr_efr = os.getenv("XREFR", "Unknown")
        self.cal_ws = os.getenv("CALWS", "Unknown")
        self.cal_efr = os.getenv("CALEFR", "Unknown")
        self.build_info = CafyReportData.build_info(self.xr_ws,
                                                    self.xr_efr,
                                                    self.cal_ws,
                                                    self.cal_efr)
        self.debug_dir = os.getenv("DEBUG_DIR", "Unknown")

        # Time
        self.pc_start = os.environ.get("PC_START")
        self.pc_stop = os.environ.get("PC_STOP")
        elapsed = datetime.now() - self.start
        self.stop_time = time.asctime(time.localtime(time.time()))
        self.run_time = self.get_readable_time(elapsed)

        # Run Info
        self.exec_host = platform.node()
        self.python_version = platform.python_version()
        self.platform = platform.platform()
        try:
            self.cafykit_release = os.path.basename(os.environ.get("VIRTUAL_ENV"))
        except:
            self.cafykit_release = None
        self.testbed = None
        self.registration_id = CafyLog.registration_id
        self.submitter = EmailReport.USER
        self.cafy_repo = EmailReport.CAFY_REPO
        self.topo_file = topo_file
        self.run_dir = self.terminalreporter.startdir.strpath
        try:
            self.git_commit_id = subprocess.check_output(['git', 'rev-parse', 'origin/master'], timeout=5).decode("utf-8").replace('\n', '')
        except Exception:
            self.git_commit_id = None
        self.archive = CafyLog.work_dir
        # summary result
        passed_list = self.terminalreporter.getreports('passed')
        failed_list = self.terminalreporter.getreports('failed')
        skipped_list = self.terminalreporter.getreports('skipped')
        xpassed_list = self.terminalreporter.getreports('xpassed')
        xfailed_list = self.terminalreporter.getreports('xfailed')

        # total_tc_list = self.terminalreporter.getreports('')
        self.passed = len(passed_list)
        self.failed = len(failed_list)
        self.skipped = len(skipped_list)
        self.xpassed = len(xpassed_list)
        self.xfailed = len(xfailed_list)
        self.total = self.passed + self.failed + self.skipped + self.xpassed + self.xfailed
        if self.terminalreporter.config.option.mail_if_fail is True and self.total == self.passed and self.total != 0:
            self.terminalreporter.config._email.no_email = True
        # testcase summary result
        self.testcase_name = testcase_dict.keys()
        if CafyLog.htmlfile_link:
            self.allure_report = CafyLog.htmlfile_link
            if CafyLog.web_host:
                self.htmlprefix = CafyLog.web_host
            else:
                if self.allure_report.startswith(('/ws', '/auto')):
                    self.htmlprefix = 'http://allure.cisco.com'
                else:
                    self.htmlprefix = 'file:///'
        else:
            self.allure_report = None

        email_html_filename = 'email_report.html'
        path = self.cafy_repo
        file_link = os.path.join(
            os.path.sep, self.archive, email_html_filename)
        if os.path.isfile(file_link):
            if CafyLog.web_host:
                html_link = os.path.join(
                        os.path.sep, CafyLog.web_host, file_link)
            else:
                if path.startswith(('/auto', '/ws')):
                    html_link = os.path.join(
                            os.path.sep, 'http://allure.cisco.com', file_link)
                else:
                    html_link = os.path.join(
                            os.path.sep, 'file:///', file_link)
            CafyLog.email_htmlfile_link = file_link
        else:
            print('\n Email html report not generated')





        if CafyLog.email_htmlfile_link:
            self.summary_report = CafyLog.email_htmlfile_link
            if CafyLog.web_host:
                self.htmlprefix = CafyLog.web_host
            else:
                if self.summary_report.startswith(('/ws', '/auto')):
                    self.htmlprefix = 'http://allure.cisco.com'
                else:
                    self.htmlprefix = 'file:///'
        else:
            self.summary_report = None

    @staticmethod
    def get_readable_time(delta):
        """
        Convert time object into a human-readable format
        """
        _m, _s = divmod(delta.seconds, 60)
        _h, _m = divmod(_m, 60)
        _d = delta.days
        if _d > 0:
            run_time = "{}d {}h".format(_d, _h)
        elif _h > 0:
            run_time = "{}h {}m".format(_h, _m)
        elif _m > 0:
            run_time = "{}m {}s".format(_m, _s)
        else:
            run_time = "{}s".format(_s)
        return run_time


class LogGrouping:
    def get_subgroupings(self):
        return []

    def get_title(self):
        pass

    def get_log_lines(self):
        pass

    def append_log_line(self, line):
        pass


class LogLine:
    def __init__(self, line, type = None):
        self.line = line
        self.type = type

class GenericLogGrouping(LogGrouping):
    def __init__(self):
        self.log_lines = []

    def get_title(self):
        if len(self.log_lines) > 0:
            return self.log_lines[0].line[0:80] + "... and " + str(len(self.log_lines)) + " more lines"
        else:
            return "Generic log line"

    def get_log_lines(self):
        return self.log_lines

    def append_log_line(self, line):
        self.log_lines.append(line)


class TestCase(LogGrouping):
    def __init__(self, name=None, description=None):
        self.name = name
        self.description = description
        self.log_lines = []
        self.failed = False

    def get_title(self):
        return 'Test case: ' + self.name + (' ***Failed***' if self.failed else '')

    def get_log_lines(self):
        return self.log_lines

    def append_log_line(self, line):
        self.log_lines.append(line)

class LogState(Enum):
    NONE = 1
    GENERIC = 2
    TESTCASE = 3
    STEP = 3
