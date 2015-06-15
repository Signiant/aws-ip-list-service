import socket
import boto.route53
import boto.ec2.elb
import boto.beanstalk
import re
from boto.s3.connection import S3Connection
from boto.s3.key import Key
import os

# List of all EIPs
def _list_eips(region, filter):
    print "Connecting to ec2..."
    conn = boto.ec2.connect_to_region(region)
    all_eips = conn.get_all_addresses()
    all_eips = [ip.public_ip for ip in all_eips if ip.public_ip not in filter]
    return all_eips

# List IP of load balancer
def _balancer_ip(lb_name):
    print "Getting load balancer IP for %s..." % lb_name
    return socket.gethostbyname_ex(lb_name)[2]

# Describe the active environment
def _environment_descr(app_name, lb_name, region):
    print "Connecting to beanstalk..."
    eb = boto.beanstalk.connect_to_region(region)
    ret = eb.describe_environments(application_name=app_name)
    ret = _decode_dict(ret)
    active_env = None
    print "Looking up active environment..."
    for env in ret['DescribeEnvironmentsResponse']['DescribeEnvironmentsResult']['Environments']:
        if lb_name in env['EndpointURL'].lower():
            active_env = env
            break
    return active_env['EndpointURL']

# Name of active load balancer
def _active_balancer(dns_name, region):
    print "Connecting to route53..."
    rconn = boto.route53.connect_to_region(region)
    zones = rconn.get_all_hosted_zones()
    zones = _decode_dict(zones)['ListHostedZonesResponse']['HostedZones']
    chosen_zone = None
    print "Looking up zone ID..."
    for zone in zones:
        if zone['Name'][:-1] in dns_name:
            chosen_zone = zone['Id'][12:]
            break
    print "Retrieving record sets..."
    rset = rconn.get_all_rrsets(chosen_zone, name=dns_name, maxitems=1)[0]
    lb_name = rset.alias_dns_name
    lb_name = re.search('dualstack.(.*)-[0-9]{9}', lb_name).group(1)
    return lb_name
    
# IPs of running instances
def _instance_ip(lb_name, region):
    print "Connecting to ec2 elb..."  
    elb = boto.ec2.elb.connect_to_region(region)
    print "Connected!"
    print "Retrieving load balancers..."
    all_lbs = elb.get_all_load_balancers()
    for lb in all_lbs:
        if lb_name in lb.name.lower():
            lb_name = str(lb.name)
            break
    print "Retrieved!"
    balancer = elb.get_all_load_balancers(lb_name)[0]
    print "Connecting to ec2 to retrieve all instances..."
    conn = boto.ec2.connect_to_region(region)
    print "Getting instances..."
    all_instances = conn.get_only_instances()
    instances = []
    print "Looping now..."
    for inst in all_instances:
        for b_inst in balancer.instances:
            if b_inst.id == inst.id:
                instances.append(
                    inst.ip_address
                )
    print "Done"
    return instances

def _get_config(bucket_name, s3_path, local_path):
    if os.path.isfile(local_path):
        print "Deleting current file..."
        os.remove(local_path)
        print "Done"
    print "Retrieving config file..."
    conn = S3Connection()
    bucket = conn.lookup(bucket_name)
    key = Key(bucket, s3_path)
    key.get_contents_to_filename(local_path)
    print "Done"

# Decode dict/list
def _decode_dict(data):
    rv = {}
    for key, value in data.iteritems():
        if isinstance(key, unicode):
            key = key.encode('utf-8')
        if isinstance(value, unicode):
            value = value.encode('utf-8')
        elif isinstance(value, list):
            value = _decode_list(value)
        elif isinstance(value, dict):
            value = _decode_dict(value)
        rv[key] = value
    return rv

def _decode_list(data):
    rv = []
    for item in data:
        if isinstance(item, unicode):
            item = item.encode('utf-8')
        elif isinstance(item, list):
            item = _decode_list(item)
        elif isinstance(item, dict):
            item = _decode_dict(item)
        rv.append(item)
    return rv
