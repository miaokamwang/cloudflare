#!/usr/bin/env python3
import requests
import json
import subprocess

# 配置文件路径
CONFIG_FILE_PATH = '/opt/crontab.py/cloudflare/cloudflare_config.json'

def load_config():
    """加载配置文件"""
    try:
        with open(CONFIG_FILE_PATH, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        return {"records": []}

def save_config(config):
    """保存配置到文件"""
    with open(CONFIG_FILE_PATH, 'w') as file:
        json.dump(config, file, indent=4)

def update_config_record(config, ipv6_patch, new_ipv6_address, zone_id=None, record_id=None):
    """根据 ipv6_patch 更新配置记录中的 last_ipv6 地址，并可选更新 zone_id 和 record_id"""
    for record in config['records']:
        if record.get('ipv6_patch') == ipv6_patch:
            record['last_ipv6'] = new_ipv6_address
            if zone_id:
                record['zone_id'] = zone_id
            if record_id:
                record['record_id'] = record_id
            save_config(config)
            print(f"Configuration updated for ipv6_patch: {ipv6_patch}.")
            return
    print(f"No matching record found in configuration for ipv6_patch: {ipv6_patch}.")

def get_public_ipv6(interface='br0'):
    """从指定接口获取IPv6地址"""
    try:
        result = subprocess.run(['ip', 'addr', 'show', interface], capture_output=True, text=True)
        ipv6_addresses = []
        for line in result.stdout.split('\n'):
            if 'inet6' in line and 'scope global dynamic' in line:
                ipv6_address = line.split()[1].split('/')[0]
                ipv6_addresses.append(ipv6_address)
        return ipv6_addresses[0] if ipv6_addresses else None
    except Exception as e:
        print(f"Error getting IPv6 address: {e}")
        return None

def combine_ipv6(ipv6_address, ipv6_patch):
    """组装IPv6地址"""
    ipv6_segments = ipv6_address.split(':')
    patch_segments = ipv6_patch.split(':')
    # 使用原IPv6地址的前四个段和ipv6_patch的后四个段
    new_ipv6 = ':'.join(ipv6_segments[:4] + patch_segments[-4:])
    return new_ipv6

def get_zone_and_record_ids(auth_email, auth_key, domain, record_name):
    """从 Cloudflare 获取 zone_id 和 record_id"""
    # Cloudflare API 的基础 URL
    base_url = "https://api.cloudflare.com/client/v4"
    
    # 设置请求头
    headers = {
        "X-Auth-Email": auth_email,
        "X-Auth-Key": auth_key,
        "Content-Type": "application/json",
    }
    
    # 获取 zone_id
    zones_url = f"{base_url}/zones?name={domain}"
    zone_response = requests.get(zones_url, headers=headers)
    zone_data = zone_response.json()
    zone_id = zone_data['result'][0]['id'] if zone_data['success'] else None
    
    if not zone_id:
        print(f"Failed to get zone_id for domain: {domain}")
        return None, None
    
    # 使用 zone_id 获取 record_id
    dns_records_url = f"{base_url}/zones/{zone_id}/dns_records?type=AAAA&name={record_name}"
    record_response = requests.get(dns_records_url, headers=headers)
    record_data = record_response.json()
    record_id = record_data['result'][0]['id'] if record_data['success'] else None
    
    if not record_id:
        print(f"Failed to get record_id for record: {record_name}")
        return zone_id, None
    
    return zone_id, record_id

def update_cloudflare_dns_record(email, api_key, zone_id, record_id, domain, ipv6_address):
    """更新Cloudflare上的DNS记录"""
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}"
    headers = {
        "X-Auth-Email": email,
        "X-Auth-Key": api_key,
        "Content-Type": "application/json",
    }
    data = {
        "type": "AAAA",
        "name": domain,
        "content": ipv6_address,
        "ttl": 300,
    }
    response = requests.put(url, headers=headers, json=data)
    return response.json()

def update_file_with_ipv6(file_path, ipv6_address):
    """将新的IPv6地址直接写入指定文件，替换其内容"""
    try:
        with open(file_path, 'w') as file:
            file.write(ipv6_address)
        print(f"File {file_path} updated with new IPv6 address: {ipv6_address}")
    except IOError as e:
        print(f"Error updating file {file_path}: {e}")

def update_hosts_file(ipv6_patch, new_ipv6_address):
    """在 /etc/hosts 中基于 ipv6_patch 匹配并更新 IPv6 地址"""
    try:
        with open('/etc/hosts', 'r') as file:
            lines = file.readlines()
        
        updated = False
        new_lines = []
        for line in lines:
            # 检查行中是否包含ipv6_patch
            if ipv6_patch in line:
                # 仅更新包含ipv6_patch的行
                parts = line.strip().split()
                # 假设IPv6地址是行中的第一个元素
                if ":" in parts[0]:  # 简单的检查以确保这看起来像是IPv6地址
                    parts[0] = new_ipv6_address  # 替换行中的IPv6地址
                    updated = True
                new_line = " ".join(parts) + "\n"
                new_lines.append(new_line)
            else:
                new_lines.append(line)
        
        if updated:
            with open('/etc/hosts', 'w') as file:
                file.writelines(new_lines)
            print("/etc/hosts successfully updated.")
        else:
            print(f"No matching entry found in /etc/hosts for the ipv6_patch: {ipv6_patch}.")

    except Exception as e:
        print(f"Error updating /etc/hosts: {e}")

def main():
    config = load_config()
    current_ipv6 = get_public_ipv6()
    if not current_ipv6:
        print("Failed to obtain IPv6 address.")
        return

    for record in config['records']:
        # 检查是否需要更新 Cloudflare DNS 记录
        if record.get('cfupdate') == "yes":
            # 如果 zone_id 或 record_id 缺失，则尝试获取它们
            if not record['zone_id'] or not record['record_id']:
                zone_id, record_id = get_zone_and_record_ids(
                    record['auth_email'], record['auth_key'], record['domain'], record['record_name'])
                
                # 如果成功获取，则更新配置记录
                if zone_id and record_id:
                    record['zone_id'] = zone_id
                    record['record_id'] = record_id
                    print(f"Successfully updated zone_id and record_id for {record['domain']}.")
                else:
                    # 如果未能获取，则跳过此记录的后续处理
                    print(f"Failed to update zone_id and record_id for {record['domain']}.")
                    continue

        # 组装新的IPv6地址
        new_ipv6 = combine_ipv6(current_ipv6, record['ipv6_patch'])
        
        # 检查是否需要更新Cloudflare DNS记录
        if record.get('cfupdate') == "yes":
            if new_ipv6 != record.get('last_ipv6'):
                result = update_cloudflare_dns_record(
                    email=record['auth_email'],
                    api_key=record['auth_key'],
                    zone_id=record['zone_id'],
                    record_id=record['record_id'],
                    domain=record['record_name'],
                    ipv6_address=new_ipv6
                )
            # 检查是否更新成功或记录已存在
                if result['success'] or ('errors' in result and any('Record already exists' in error['message'] for error in result['errors'])):
                    print(f"DNS record updated for {record['record_name']}.")
                    update_config_record(config, record['ipv6_patch'], new_ipv6)
                else:
                    print(f"Failed to update DNS record for {record['record_name']}. Error: {result.get('errors', 'Unknown error')}")
            else:
                print(f"No changes in IPv6 address for {record['record_name']}, skipping DNS update.")

         # 不管是否更新了Cloudflare DNS记录，都尝试更新本地文件
        if record.get('hostupdate') == "yes":
             update_hosts_file(record['ipv6_patch'], new_ipv6)

        # 不管是否更新了Cloudflare DNS记录，都尝试更新本地文件
        update_file_with_ipv6(record['file_patch'], new_ipv6)
        # 更新配置中的last_ipv6
        if new_ipv6 != record.get('last_ipv6'):
            update_config_record(config, record['ipv6_patch'], new_ipv6)

    # 保存配置
    save_config(config)

if __name__ == "__main__":
    main()
