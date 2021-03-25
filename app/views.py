from . import awslib
from app import app
from flask import render_template
from flask import send_from_directory
import json
import yaml
from json import dumps
from os.path import join
from flask import make_response, request, redirect, url_for
import os, time
import traceback

bucket_name = os.environ.get('IPLIST_CONFIG_BUCKET')
s3path = os.environ.get('IPLIST_CONFIG_PATH')
nohttps = os.environ.get('NOHTTPS')

path = join('iplist_config', 'config')

if s3path == None:
    print ("No Env Labeled IPLIST_CONFIG_PATH")
elif bucket_name == None:
    print ("No bucket name specified")
else:
    awslib.get_file(bucket_name, s3path, path)
#####
# Caching parameters
#####
cache_timeout_period_in_seconds = 300
cache_root_directory = "/ip-range-cache"

try:
    os.makedirs(cache_root_directory)
except:
    pass


@app.route('/')
def handle_index():
    redir = None
    if nohttps == None:
        proto = request.headers.get("X-Forwarded-Proto")
        if not proto == "https":
            redir = _check_ssl(request.url)

    if not redir == None:
        return redir

    with open(path) as config_data:
        # This should handle json or yaml
        data = yaml.safe_load(config_data)

    app_data = []
    hidden_apps = []
    alt_apps = []
    for app in data['apps']:
        # altname list for deprecated url links
        if app.get('altname'):
            app_info = {}
            app_info['name'] = app['altname']
            app_info['additionalText'] = ''
            alt_apps.append(app_info)
        if app.get('hidden'):
            print('Found hidden app: %s' % app['name'])
            app_info = {}
            app_info['name'] = app['name']
            app_info['additionalText'] = ''
            if app.get('additionalText'):
                app_info['additionalText'] = app['additionalText']
            hidden_apps.append(app_info)
        else:
            app_info = {}
            app_info['name'] = app['name']
            app_info['additionalText'] = ''
            if app.get('additionalText'):
                app_info['additionalText'] = app['additionalText']
            app_data.append(app_info)

    return render_template("index.html", apps=app_data, altapps=alt_apps, hidden=hidden_apps)


@app.route('/healthcheck')
def handle_healthcheck():
    print("I'm still here. test")
    return render_template("healthcheck.html")


def _read_from_cache(app_cache_file):
    read_from_cache = True
    try:
        print(app_cache_file)
        with open(app_cache_file, "r") as cache:
            cache_time = float(cache.readline().strip())
            current_time = time.time()
            if (current_time - cache_time) > cache_timeout_period_in_seconds:
                read_from_cache = False
    except IOError:
        read_from_cache = False
    return read_from_cache


@app.route('/all')
def handle_all_app():
    with open(path) as config_data:
        # This should handle json or yaml
        data = yaml.safe_load(config_data)

    app_name_list = []
    for app in data['apps']:
        app_name_list.append(app['name'])

    output=""
    all_list={}
    for app_name in app_name_list:
        verbose = False
        chosen_region = None
        query_string = request.query_string
        modified_date = None
        if not query_string == "":
            for query in query_string.split(b'&'):
                if b'verbose' in query.lower():
                    if query.endswith(b'1'):
                        verbose = True
                elif b'region' in query.lower():
                    chosen_region = query[7:].decode("utf-8")
        suffix = ".json"

        if verbose:
            suffix = ".verbose" + suffix

        if chosen_region:
            suffix = "." + chosen_region + suffix

        app_cache_file = os.path.join(cache_root_directory, app_name.lower() + suffix)
        app_cache_file = parse_data_from_file(app_name, chosen_region, app_cache_file, verbose)

        with open(app_cache_file, "r") as cache:
            # read the first line as cache time
            cache_time = cache.readline()
            line = cache.readline()

            print("every_line {0}".format(line))
            print("every_line_type {0}".format(type(line)))
            # print("jsonify everyline {0}".format(jsonify(**eval(line))))
            all_list[app_name]=eval(line)
            output = output + line
    # print("all output together {0}".format(output))
    print("all_output_list {0}".format(all_list))
    print("all_output_type {0}".format(type(all_list)))
    # print("jsonify_output {0}".format(jsonify(**eval(all_list))))

        # return jsonify(**eval(line))

    return jsonify(**all_list)

@app.route('/<appname>')
def handle_app(appname):
    verbose = False
    chosen_region = None
    query_string = request.query_string
    modified_date = None
    if not query_string == "":
        for query in query_string.split(b'&'):
            if b'verbose' in query.lower():
                if query.endswith(b'1'):
                    verbose = True
            elif b'region' in query.lower():
                chosen_region = query[7:].decode("utf-8")
    suffix = ".json"

    if verbose:
        suffix = ".verbose" + suffix

    if chosen_region:
        suffix = "." + chosen_region + suffix

    app_cache_file = os.path.join(cache_root_directory,appname.lower() + suffix)

    if _read_from_cache(app_cache_file):
        print("Reading cached data for this request.")
    else:
        print("Cache is out of date. Refreshing for this request.")

        app_cache_file = parse_data_from_file(appname, chosen_region, app_cache_file, verbose)

    with open(app_cache_file, "r") as cache:
        # read the first line as cache time
        cache_time = cache.readline()
        line = cache.readline()
        return jsonify(**eval(line))


@app.route('/service-list')
def handle_service_list():
    verbose = False
    chosen_service = None
    query_string = request.query_string

    if not query_string == "":
        for query in query_string.split(b'&'):
            if b'verbose' in query.lower():
                if query.endswith(b'1'):
                    verbose = True
            elif b'service' in query.lower():
                chosen_service = query[8:].decode("utf-8")
    suffix = ".json"

    if verbose:
        suffix = ".verbose" + suffix

    if chosen_service:
        suffix = "." + chosen_service + suffix

    print("Getting service list")

    cache_file = os.path.join(cache_root_directory, 'service-list' + suffix)

    if _read_from_cache(cache_file):
        print("Reading cached data for this request.")
    else:
        print("Cache is out of date. Refreshing for this request.")

        try:
            with open(path) as config_data:
                # This should handle json or yaml
                data = yaml.safe_load(config_data)

            if verbose:
                print (request.url)
            redir = None
            if nohttps is None:
                proto = request.headers.get("X-Forwarded-Proto")
                if not proto == "https":
                    redir = _check_ssl(request.url, verbose)
            if redir is not None:
                return redir

            ret = {}
            for app in data['apps']:
                display = app.get('service_list')
                if not display:
                    # skip this
                    continue

                app_name = app.get('name')

                # only run next section if specific service NOT chosen
                if chosen_service:
                    if app_name != chosen_service:
                        continue

                app_config = app.get('config')
                region_list = []
                for config in app_config:
                    if config.get('R53'):
                        region_list = []
                        for item in config['R53']:
                            region_name = item.get('Name')
                            if region_name not in region_list:
                                region_list.append(region_name)
                    elif config.get('S3'):
                        for item in config['S3']:
                            region_name = item.get('region')
                            if region_name not in region_list:
                                region_list.append(region_name)
                    else:
                        region_name = config.get('region')
                        if region_name not in region_list:
                            region_list.append(region_name)

                ret[app_name] = region_list

            if not ret:
                return redirect(url_for('handle_index'), code=302)
            else:
                _write_cache(cache_file, ret)
        except:
            print ("Error: Unable to load new information")
            traceback.print_exc()

    with open(cache_file, "r") as cache:
        # read the first line as cache time
        cache_time = cache.readline()
        line = cache.readline()
        return jsonify(**eval(line))


def ip_list_sort(ret):
    """
    sort ips in the nested dict list
    :param ret:
    :return:
    """
    for region in ret:
        for ip_list in ret[region]:
            if ip_list == "all_ips":
                # Remove any duplicates
                ret[region][ip_list] = list(set(ret[region][ip_list]))
                ret[region][ip_list].sort()
    return ret


@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'favicon.ico', mimetype='image/vnd.microsoft.icon')


def jsonify(status=200, indent=4, sort_keys=False, **kwargs):
    response = make_response(dumps(dict(**kwargs), indent=indent, sort_keys=sort_keys))
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    response.headers['mimetype'] = 'application/json'
    response_code = status
    return response


def _check_ssl(url, verbose=False):
    if verbose:
        print ("Current scheme: %s" % url[:5])
    if url[:5] == "https":
        return None
    else:
        return redirect("https" + url[4:], code=302)


def _write_cache(app_cache_file,data):
    with open(app_cache_file, "w+") as cache:
        cache.write(str(time.time()))
        cache.write("\n")
        cache.write(str(data))


def parse_data_from_file(appname, chosen_region, app_cache_file, verbose):
    try:
        with open(path) as config_data:
            # This should handle json or yaml
            data = yaml.safe_load(config_data)

        ret = {}

        if verbose:
            print(request.url)
        redir = None
        if nohttps == None:
            proto = request.headers.get("X-Forwarded-Proto")
            if not proto == "https":
                redir = _check_ssl(request.url, verbose)
        if not redir == None:
            return redir
        for app in data['apps']:
            # create url link for both name and alternative name for ip-range apps
            if appname.lower() == app['name'].lower() or appname.lower() == str(app.get('altname')).lower():
                app_config = app['config']

                for config in app_config:

                    if config.get('s3filepath'):
                        datapath = config.get('localpath')
                        awslib.get_file(bucket_name, config['s3filepath'], datapath)
                        with open(datapath) as filedata:
                            output = json.load(filedata)
                        break
                    elif config.get('R53'):
                        ret = {}
                        for item in config['R53']:
                            print('Getting records for %s' % item['Name'])
                            ret[item['Name']] = {}

                            ret[item['Name']]['all_ips'] = []
                            ret[item['Name']]['all_ips'] = awslib.get_records_from_zone(item['HostedZoneId'],
                                                                                        item['Pattern'])
                            if 'last_modified' in item:
                                modified_date = str(item['last_modified'])
                                ret[item['Name']]['last_modified'] = modified_date
                            inclusions = item.get('inclusions')
                            if inclusions:
                                print('Adding inclusions from config')
                                if 'dns_list' in inclusions:
                                    for dns in inclusions['dns_list']:
                                        dns_ips = awslib.list_balancer_ips(dns)
                                        ret[item['Name']]['all_ips'].extend(dns_ips)
                                if 'ip_list' in inclusions:
                                    ret[item['Name']]['all_ips'].extend(inclusions['ip_list'])
                        break
                    elif config.get('S3'):
                        ret = {}
                        for item in config['S3']:
                            print('Getting records for %s' % item['Name'])
                            bucket_name = item.get('bucket')
                            object_path = item.get('objectpath')
                            region = item.get('region')
                            ret[item['Name']] = {}
                            ret[item['Name']]['all_ips'] = []
                            if 'last_modified' in item:
                                modified_date = str(item['last_modified'])
                                ret[item['Name']]['last_modified'] = modified_date
                            ret[item['Name']]['last_modified'] = modified_date
                            if bucket_name and object_path and region:
                                file_contents = awslib.get_file_contents(bucket_name, object_path)
                                region_data = file_contents.get(region)
                                ret[item['Name']]['all_ips'] = region_data
                            inclusions = item.get('inclusions')
                            if inclusions:
                                print('Adding inclusions from config')
                                if 'dns_list' in inclusions:
                                    for dns in inclusions['dns_list']:
                                        dns_ips = awslib.list_balancer_ips(dns)
                                        ret[item['Name']]['all_ips'].extend(dns_ips)
                                if 'ip_list' in inclusions:
                                    ret[item['Name']]['all_ips'].extend(inclusions['ip_list'])
                        break

                    region = config['region']

                    # only run next section if region equal chosen_region
                    if chosen_region:
                        if chosen_region != region:
                            continue

                    dnsname = config.get('dnsname')
                    inclusions = config.get('inclusions')
                    exclusions = config.get('exclusions')
                    eip_check = config.get('show_eip')
                    lb_check = config.get('show_lb_ip')
                    inst_check = config.get('show_inst_ip')
                    modified_date = config.get('last_modified')
                    if not ret.get(region):
                        ret[region] = {}
                        if 'last_modified' in config:
                            modified_date = str(config.get('last_modified'))
                            ret[region]['last_modified'] = modified_date
                    if not ret[region].get('all_ips'):
                        ret[region]['all_ips'] = []

                    if eip_check:
                        eips = awslib.list_eips(region, filter=exclusions)
                        # verbose only makes sense if we're not getting ALL EIPs
                        if verbose:
                            if not ret[region].get('eips'):
                                ret[region]['eips'] = eips
                            else:
                                ret[region]['eips'].extend(eips)

                        if eip_check:
                            ret[region]['all_ips'].extend(eips)

                    if lb_check:
                        elb = awslib.list_balancer_ips(dnsname)

                        if verbose:
                            if not ret[region].get('elb'):
                                ret[region]['elb'] = elb
                            else:
                                ret[region]['elb'].extend(elb)

                        if lb_check:
                            ret[region]['all_ips'].extend(elb)

                    if inst_check:
                        lb_names = config.get('lb_names')
                        lb_name = None
                        if not lb_names:
                            lb_name = awslib.get_active_balancer(dnsname, region)

                        if not lb_name and not lb_names:
                            print('ERROR: Unable to determine LB name(s) - cannot get instance IPs')
                        else:
                            if not lb_names:
                                lb_names = [lb_name]
                            for lb in lb_names:
                                inst_ips = awslib.list_instance_ips(lb.lower(), region)
                                if verbose:
                                    if not ret[region].get('instance_ips'):
                                        ret[region]['instance_ips'] = inst_ips
                                    else:
                                        ret[region]['instance_ips'].extend(inst_ips)

                                if inst_check:
                                    ret[region]['all_ips'].extend(inst_ips)

                    if inclusions:
                        print('Adding inclusions from config')
                        if 'dns_list' in inclusions:
                            for dns in inclusions['dns_list']:
                                dns_ips = awslib.list_balancer_ips(dns)
                                if verbose:
                                    if not ret[region].get('inclusions'):
                                        ret[region]['inclusions'] = dns_ips
                                    else:
                                        ret[region]['inclusions'].extend(dns_ips)
                                ret[region]['all_ips'].extend(dns_ips)
                        if 'ip_list' in inclusions:
                            if verbose:
                                if not ret[region].get('inclusions'):
                                    ret[region]['inclusions'] = inclusions['ip_list']
                                else:
                                    ret[region]['inclusions'].extend(inclusions['ip_list'])
                            ret[region]['all_ips'].extend(inclusions['ip_list'])

        if not ret:
            return redirect(url_for('handle_index'), code=302)
        else:
            # sort ip list in ret when it can
            ret = ip_list_sort(ret)
            _write_cache(app_cache_file, ret)
    except:
        print("Error: Unable to load new information for app: " + str(appname))
        traceback.print_exc()

    return app_cache_file
