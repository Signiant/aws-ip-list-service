import boto3
import re
import os
import socket
import json


# List of all EIPs in the given region
def list_eips(region, filter):
    all_eips = []
    print("Connecting to ec2...")
    client = boto3.client('ec2', region_name=region)
    if client:
        # print("Connected!")
        print("Getting all EIPs in region %s" % region)
        addresses_dict = client.describe_addresses()
        for eip_dict in addresses_dict['Addresses']:
            if eip_dict['PublicIp'] not in filter:
                all_eips.append(eip_dict['PublicIp'])
    return all_eips


# List IPs of load balancer
def list_balancer_ips(dns_name):
    print ("  Getting IP(s) for URL %s..." % dns_name)
    return socket.gethostbyname_ex(dns_name)[2]


# Name of active load balancer
def get_active_balancer(dns_name, region):
    print('Finding the active load balancer behind %s' % dns_name)
    lb_name = None
    print("Connecting to route53...")
    r53_client = boto3.client('route53', region_name=region)
    if r53_client:
        # print("Connected!")
        zones = r53_client.list_hosted_zones()
        chosen_zone = None
        print("Looking up zone ID...")

        temp_dns_name = dns_name.split('.', 1)[-1]
        print("Temp dns_name is %s" % temp_dns_name)

        for zone in zones['HostedZones']:
            # print ("The zone is: %s, the dns_name is %s" % (zone['Name'][:-1], dns_name))
            if zone['Name'][:-1] == dns_name:
                print("Found zone that equals the dns name: %s" % zone['Name'])
                chosen_zone = zone['Id'][12:]
                break

            elif zone['Name'][:-1] == temp_dns_name:
                print("Found zone that equals the temp dns name: %s" % zone['Name'])
                chosen_zone = zone['Id'][12:]

        if chosen_zone:
            print("Retrieving record sets...")
            rset = r53_client.list_resource_record_sets(HostedZoneId=chosen_zone,
                                                        StartRecordName=dns_name,
                                                        StartRecordType="A",
                                                        MaxItems="1")['ResourceRecordSets'][0]
            print("Record set retrieved is : ")
            print(rset)
            if 'AliasTarget' in rset:
                lb_name = rset['AliasTarget']['DNSName']

                if lb_name.startswith("dualstack"):
                    lb_name = lb_name.split("dualstack.")[1]

                # Split on periods, take the first group (lbname dns), split on hyphens and take all but the end and rejoin with hyphens
                lb_name = "-".join(lb_name.split(".")[0].split("-")[:-1])

                print("Retrieved load-balancer: " + str(lb_name))
    else:
        print("ERROR: Failed to connect to R53")

    return lb_name


# All Classic load balancers
def _get_v1_lbs(elb_client, next_marker=None):
    """Get the v1 ELBs"""
    result = []
    if next_marker:
        query_result = elb_client.describe_load_balancers(Marker=next_marker)
    else:
        query_result = elb_client.describe_load_balancers()

    if 'NextMarker' in query_result:
        result.extend(query_result['LoadBalancerDescriptions'])
        result.extend(_get_v1_lbs(elb_client, next_marker=query_result['NextMarker']))
    else:
        result.extend(query_result['LoadBalancerDescriptions'])
    return result


# All Application and Network load balancers
def _get_v2_lbs(elb_client, next_marker=None):
    """Get the v2 ELBs"""
    result = []
    if next_marker:
        query_result = elb_client.describe_load_balancers(Marker=next_marker)
    else:
        query_result = elb_client.describe_load_balancers()

    if 'NextMarker' in query_result:
        result.extend(query_result['LoadBalancers'])
        result.extend(_get_v2_lbs(elb_client, next_marker=query_result['NextMarker']))
    else:
        result.extend(query_result['LoadBalancers'])
    return result


# Get all instances in a target group
def _get_instances_for_target_group(elbv2, tg_arn, target_type, region):
    instances = []
    ec2_client = boto3.client('ec2', region_name=region)
    if ec2_client:
        tg_health_desc = elbv2.describe_target_health(TargetGroupArn=tg_arn)
        if 'instance' in target_type:
            print('Target Type is instance - can get the instances directly from this target group')
            found_instances = [inst['Target']['Id'] for inst in tg_health_desc['TargetHealthDescriptions']]
            print("Instances discovered: %s" % str(found_instances))
            instances.extend(found_instances)
        elif 'ip' in target_type:
            print('Target Type is ip - need to determine what the IP is attached to')
            for target in tg_health_desc['TargetHealthDescriptions']:
                ip = target['Target']['Id']
                filter = {'Name': 'addresses.private-ip-address', 'Values': [ip]}
                query_result = ec2_client.describe_network_interfaces(Filters=[filter])
                if 'NetworkInterfaces' in query_result:
                    nic_details = query_result['NetworkInterfaces'][0]
                    # Make sure this is an ELB
                    if 'amazon-elb' in nic_details['Attachment']['InstanceOwnerId']:
                        # get the lb_name this IP is attached to
                        # 'ELB app/awseb-AWSEB-19KDLWH6ZMJA2/f8992902ed546a45'
                        interface_description = nic_details['Description']
                        lb_name = interface_description.split('/')[1]
                        print('Given IP target is attached to load balancer with name: %s' % lb_name)
                        query_result = elbv2.describe_load_balancers(Names=[lb_name])
                        if 'LoadBalancers' in query_result:
                            lb_details = query_result['LoadBalancers'][0]
                            lb_arn = lb_details['LoadBalancerArn']
                            # Get the target groups for this load balancer
                            response = elbv2.describe_target_groups(LoadBalancerArn=lb_arn)
                            if 'TargetGroups' in response:
                                lb_tgs = response['TargetGroups']
                                # print('LB Target Groups: %s' % str(lb_tgs))
                                for tg in lb_tgs:
                                    # print("target group: %s" % str(tg))
                                    tg_arn = tg['TargetGroupArn']
                                    target_type = tg['TargetType']
                                    instances.extend(_get_instances_for_target_group(elbv2, tg_arn, target_type, region))
        else:
            print('Target Type is: %s - unhandled' % target_type)
    else:
        print("ERROR: Failed to connect to EC2")

    return list(set(instances))


# Get the public IPs for the given instances
def _get_instances_public_ip(ec2_client, instances):
    instance_ips = []
    reservations = ec2_client.describe_instances(InstanceIds=instances)['Reservations']
    for r in reservations:
        for instance in r['Instances']:
            if 'PublicIpAddress' in instance:
                instance_ips.append(instance['PublicIpAddress'])
            else:
                print("The instance %s has no public IP" % str(instance['InstanceId']))
    return list(set(instance_ips))


# IPs of running instances
def list_instance_ips(lb_name, region):
    print("Looking for instances behind load balancer %s..." % lb_name)
    instance_ips = []
    lb_found = False
    print("Connecting to ec2 elb v1...")
    elbv1 = boto3.client('elb', region_name=region)
    if elbv1:
        # print("Connected!")
        print("Retrieving classic load balancers...")
        v1_lbs = _get_v1_lbs(elbv1, next_marker=None)
        ec2_client = boto3.client('ec2', region_name=region)
        if ec2_client:
            for lb in v1_lbs:
                if lb_name in lb['LoadBalancerName'].lower():
                    print("Found the load balancer")
                    print("Processing instances for ELB %s" % lb['LoadBalancerName'])
                    instances = [inst['InstanceId'] for inst in lb['Instances']]
                    print("Instances discovered: %s" % str(instances))
                    if instances:
                        instance_ips.extend(_get_instances_public_ip(ec2_client, instances))
                    lb_found = True
                    break
            # Only look at v2 load balancers if we haven't already found the load balancer above
            if not lb_found:
                print("Didn't find the load balancer in the list of classic load balancers")
                print("Connecting to ec2 elb v2...")
                elbv2 = boto3.client('elbv2', region_name=region)
                if elbv2:
                    # print("Connected!")
                    print("Retrieving V2 load balancers...")
                    v2_lbs = _get_v2_lbs(elbv2, next_marker=None)
                    for lb in v2_lbs:
                        if lb_name in lb['LoadBalancerName'].lower():
                            print("Found the load balancer")
                            print("Processing target groups for %s" % lb['LoadBalancerName'])
                            lb_arn = lb['LoadBalancerArn']
                            # Get the target groups for this load balancer
                            response = elbv2.describe_target_groups(LoadBalancerArn=lb_arn)
                            if 'TargetGroups' in response:
                                lb_tgs = response['TargetGroups']
                                # print('LB Target Groups: %s' % str(lb_tgs))
                                for tg in lb_tgs:
                                    # print("target group: %s" % str(tg))
                                    tg_arn = tg['TargetGroupArn']
                                    target_type = tg['TargetType']
                                    instances = _get_instances_for_target_group(elbv2, tg_arn, target_type, region)
                                    if instances:
                                        instance_ips.extend(_get_instances_public_ip(ec2_client, instances))
                            lb_found = True
                            break
                    if not lb_found:
                        print("Didn't find the load balancer in the list of application/network load balancers")
                else:
                    print("ERROR: Failed to connect to ELBV2")
        else:
            print("ERROR: Failed to connect to EC2")
    else:
        print("ERROR: Failed to connect to ELB")
    return instance_ips


# Get a file from S3
def get_file(bucket_name, s3_path, local_path):
    result = False
    if os.path.isfile(local_path):
        print("Deleting current file...")
        os.remove(local_path)
        print("Done")
    print("Retrieving config file...")
    s3 = boto3.resource('s3')
    s3.Bucket(bucket_name).download_file(s3_path, local_path)
    print("Done")
    if os.path.exists(local_path):
        result = True
    return result

# Get a file date from S3
def get_file_date(bucket_name, s3_path):
    print("Retrieving config file date...")
    s3 = boto3.resource('s3')
    file_object = s3.Object(bucket_name,s3_path)
    file_date = file_object.last_modified
    print("Done")
    return file_date


# Get json file contents from S3
def get_file_contents(bucket_name, s3_path):
    result = None
    print(f"Retrieving config file ({bucket_name}/{s3_path})")
    session = boto3.session.Session()
    s3_client = session.client('s3')
    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=s3_path)
        if 'Body' in response:
            result = json.loads(response['Body'].read().decode())
    except Exception as e:
        print(f"Exception fetching S3 object ({bucket_name}/{s3_path})" + str(e))
    print("Done")
    return result


def get_all_records(r53_client, zone_id, start_record_name=None, start_record_type=None, start_record_identifier=None):
    result = []
    query_result = None
    if start_record_identifier:
        query_result = r53_client.list_resource_record_sets(HostedZoneId=zone_id,
                                                            StartRecordName=start_record_name,
                                                            StartRecordType=start_record_type,
                                                            StartRecordIdentifier=start_record_identifier)
    else:
        if start_record_name:
            query_result = r53_client.list_resource_record_sets(HostedZoneId=zone_id,
                                                                StartRecordName=start_record_name,
                                                                StartRecordType=start_record_type)
        else:
            query_result = r53_client.list_resource_record_sets(HostedZoneId=zone_id)
    if query_result:
        if 'IsTruncated' in query_result and query_result['IsTruncated']:
            # print('Found %s records' % query_result['MaxItems'])
            s_r_n = query_result['NextRecordName']
            s_r_t = query_result['NextRecordType']
            s_r_i = None
            if 'NextRecordIdentifier' in query_result:
                s_r_i = query_result['NextRecordIdentifier']
            result.extend(query_result['ResourceRecordSets'])
            result.extend(get_all_records(r53_client, zone_id, s_r_n, s_r_t, s_r_i))
        else:
            # print('Found %s records' % query_result['MaxItems'])
            result.extend(query_result['ResourceRecordSets'])
    return result


# Return prefixed record sets of a hosted zone ID
def get_records_from_zone(zone_id, record_prefixes):
    print("  Enter get records from zone")
    entries = []
    r53_client = boto3.client('route53')
    if r53_client:
        #Kinda hacky to support both arrays and strings as a value
        if not isinstance(record_prefixes, list):
            record_prefixes = [record_prefixes]
        print("  record_prefixes: " + str(record_prefixes))
        # Get all records:
        resource_record_sets = get_all_records(r53_client, zone_id)
        print('  Found %s resource records for zone %s' % (str(len(resource_record_sets)), zone_id))
        for record in resource_record_sets:
            for prefix in record_prefixes:
                try:
                    if re.match(prefix,record['Name']):
                        if 'ResourceRecords' in record:
                            entry = record['ResourceRecords'][0]['Value']
                            # Check if it's not an IP address.. Since the way this is coded it's easier than
                            # checking the type (we're searching for an A record)
                            if not re.match("^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$",entry):
                                try:
                                    for addr in [str(i[4][0]) for i in socket.getaddrinfo(entry, 80)]:
                                        if addr not in entries:
                                            entries.append(addr)
                                # Nothing we can do
                                except Exception:
                                    continue
                            else:
                                entries.append(entry)
                except Exception:
                    print('  Exception trying to match records')
                    continue
    print('  Found %s records that match given prefix' % (str(len(set(entries)))))
    return list(set(entries))


def get_zone_records(zone_id):
    resource_record_sets = []
    r53_client = boto3.client('route53')
    if r53_client:
        resource_record_sets = get_all_records(r53_client, zone_id)
    return resource_record_sets


# Given a list of resource record sets, return prefixed record sets matching given prefix(es)
def get_matching_records(resource_record_sets, record_prefixes):
    entries = []
    if not isinstance(record_prefixes, list):
        record_prefixes = [record_prefixes]
    print(f"  record_prefixes: {record_prefixes}")
    for record in resource_record_sets:
        for prefix in record_prefixes:
            try:
                if re.match(prefix, record['Name']):
                    if 'ResourceRecords' in record:
                        entry = record['ResourceRecords'][0]['Value']
                        # Check if it's not an IP address.. Since the way this is coded it's easier than
                        # checking the type (we're searching for an A record)
                        if not re.match("^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$", entry):
                            try:
                                for address in [str(i[4][0]) for i in socket.getaddrinfo(entry, 80)]:
                                    if address not in entries:
                                        entries.append(address)
                            # Nothing we can do
                            except Exception:
                                continue
                        else:
                            entries.append(entry)
            except Exception:
                print('  Exception trying to match records')
                continue

    print('  Found %s records that match given prefix' % (str(len(set(entries)))))
    return list(set(entries))
