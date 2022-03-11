from __future__ import (unicode_literals, absolute_import, print_function, division)

import configparser
import logging
import re
from time import sleep

import coloredlogs
import paramiko
import requests
from paramiko.client import AutoAddPolicy
from telegram.ext import Updater


def get_config():
    config = configparser.ConfigParser()
    config.read('config/config.ini')
    return config


def launch_phoenix_monitoring():
    config = get_config()
    logging.info('Starting phoenix monitoring - schedulerIntervalInSeconds [%s]',
                 config['default']['SchedulerIntervalInSeconds'])

    while True:
        launch_phoenix_api_analyzer()
        sleep(int(config['default']['SchedulerIntervalInSeconds']))


def launch_phoenix_api_analyzer():
    config = get_config()
    ssh_host = config['ssh']['Host']
    ssh_port = int(config['ssh']['Port'])
    ssh_login = config['ssh']['Login']
    ssh_password = config['ssh']['Password']
    maximum_invalid_share_alert = int(config['default']['MaximumInvalidShareAlert'])

    gpu_dict = {}
    gpu_index_array = []

    updater = Updater(config['telegram']['BotToken'])

    response = requests.get(config['default']['Url'])
    lines = response.text.split('\r\n')
    for line in reversed(lines):
        match_gpu_specifications = re.match(
            '^<font color=\"#55FF55\">GPU([0-9]+): (.*?) \(pcie ([0-9]+)\), (.*?), ([0-9]+) GB VRAM, ([0-9]+) CUs</font><br>$',
            line)
        if match_gpu_specifications:
            gpu_dict[match_gpu_specifications.group(1)] = {}
            gpu_dict[match_gpu_specifications.group(1)]['name'] = match_gpu_specifications.group(2)
    for line in reversed(lines):
        match_gpu_hashrate = re.match(
            '^<font color=\"#55FFFF\">GPUs:(( [0-9]+: [0-9]+\.[0-9]+ MH/s \([0-9]+/?([0-9]+)?\))+)</font><br>$',
            line)
        if match_gpu_hashrate:
            match_single_gpu_hashrate = re.compile('([0-9]+): ([0-9]+\.[0-9]+) MH/s \(([0-9]+)/?([0-9]+)?\)')
            for match in re.finditer(match_single_gpu_hashrate, match_gpu_hashrate.group(1)):
                gpu_id = match.group(1)
                gpu_dict[gpu_id]['hashrate'] = float(match.group(2))
                gpu_dict[gpu_id]['valid_shares'] = int(match.group(3))
                if match.group(4):
                    gpu_dict[gpu_id]['invalid_shares'] = int(match.group(4))
                gpu_index_array.append(gpu_id)
            break

    has_hashrate_alert = False
    has_invalid_share_alert = False
    gpu_synthesis_message = ""
    for i in gpu_index_array:
        current_gpu_dict = gpu_dict[i]
        gpu_synthesis_message += '\n' + str(current_gpu_dict['name']) + ' '

        if 'gpu.' + i in config:
            current_gpu_config = config['gpu.' + i]
            if "invalid_shares" in current_gpu_dict:
                if current_gpu_dict['invalid_shares'] > maximum_invalid_share_alert:
                    has_invalid_share_alert = True
                    gpu_synthesis_message += '❌ '
            if current_gpu_dict['hashrate'] != 0 \
                    and current_gpu_dict['hashrate'] < float(current_gpu_config['MinimumHashrateAlert']):
                has_hashrate_alert = True
                gpu_synthesis_message += '♻ '
                ssh_client = paramiko.SSHClient()
                ssh_client.set_missing_host_key_policy(AutoAddPolicy())
                ssh_client.load_system_host_keys()
                ssh_client.connect(ssh_host, ssh_port, ssh_login, ssh_password)
                ssh_client.exec_command(current_gpu_config['MinimumHashrateCommand'])
                ssh_client.close()

        gpu_synthesis_message += '\n'
        gpu_synthesis_message += '  #️⃣ hashrate | <code>' + str(current_gpu_dict['hashrate']) + '</code>' + '\n'
        gpu_synthesis_message += '  ✅ valid shares | <code>' + str(current_gpu_dict['valid_shares']) + '</code>' + '\n'
        if "invalid_shares" in current_gpu_dict:
            gpu_synthesis_message += '  ⚠ invalid shares | <code>' + str(
                current_gpu_dict['invalid_shares']) + '</code>' + '\n'

    if has_invalid_share_alert:
        error_message = 'One or more GPU have been reached invalid share threshold\n'
        error_message += gpu_synthesis_message
        updater.bot.sendMessage(chat_id=config['telegram']['ChatId'], text=error_message, parse_mode='HTML')
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(AutoAddPolicy())
        ssh_client.load_system_host_keys()
        ssh_client.connect(ssh_host, ssh_port, ssh_login, ssh_password)
        ssh_client.exec_command(config['ssh']['MaximumInvalidShareCommand'])
        ssh_client.close()

    elif has_hashrate_alert:
        error_message = 'One or more GPU have been reached minimum hashrate threshold\n'
        error_message += gpu_synthesis_message
        updater.bot.sendMessage(chat_id=config['telegram']['ChatId'], text=error_message, parse_mode='HTML')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.ERROR)
    coloredlogs.install()

    launch_phoenix_monitoring()
