import awslib
from app import app
from flask import render_template
from flask import send_from_directory
import json
from json import dumps
from os.path import join
from flask import make_response, request, redirect, url_for
import os, time, pickle
import traceback

bucket_name = os.environ.get('IPLIST_CONFIG_BUCKET')
s3path = os.environ.get('IPLIST_CONFIG_PATH')
nohttps = os.environ.get('NOHTTPS')

path = join('iplist_config', 'config.json')

if s3path == None:
    print ("No Env Labeled IPLIST_CONFIG_PATH")
elif bucket_name == None:
    print ("No bucket name specified")
else:
    awslib._get_file(bucket_name, s3path, path)

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

    with open(path) as json_data:
        data = json.load(json_data)

    return render_template("index.html", apps=[app['name'] for app in data['apps']])

@app.route('/healthcheck')
def handle_healthcheck():
    return "I'm still here. test"

@app.route('/<appname>')
def handle_app(appname):
    verbose = False
    chosen_region = None
    query_string = request.query_string

    if not query_string == "":
        for query in query_string.split('&'):
            if "verbose" in query.lower():
                if query.endswith("1"):
                    verbose = True
            elif "region" in query.lower():
                chosen_region = query[7:]
    suffix = ".json"

    if verbose:
        suffix = ".verbose" + suffix

    if chosen_region:
        suffix = "." + chosen_region + suffix

    app_cache_file = os.path.join(cache_root_directory,appname.lower() + suffix)
    read_from_cache = True
    try:
        with open(app_cache_file, "r") as cache:
            cache_time = float(cache.readline().strip())
            current_time = time.time()
            if (current_time - cache_time) > cache_timeout_period_in_seconds:
                read_from_cache = False
    except IOError:
        read_from_cache = False

    if read_from_cache:
        print("Reading cached data for this request.cd .")
    else:
        print("Cache is out of date. Refreshing for this request.")

        try:
            with open(path) as json_data:
                data = json.load(json_data)

            ret = {}

            if verbose:
                print (request.url)
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
                            awslib._get_file(bucket_name, config['s3filepath'], datapath)
                            with open(datapath) as filedata:
                                output = json.load(filedata)
                            break
                        elif config.get('R53'):
                            ret = {}
                            for item in config['R53']:
                                ret[item['Name']] = {}
                                ret[item['Name']]['all_ips'] = []
                                ret[item['Name']]['all_ips'] = awslib._get_records_from_zone(item['HostedZoneId'], item['Pattern'], item['Domain'])
                            break

                        dnsname = config['dnsname']
                        bs_app = config['beanstalk_app_name']
                        region = config['region']

                        # only run next section if region equal chosen_region
                        if chosen_region:
                            if chosen_region != region:
                                continue

                        exclusions = config['exclusions']
                        eip_check = config.get('show_eip')
                        lb_check = config.get('show_lb_ip')
                        inst_check = config.get('show_inst_ip')
                        if ret.get(region) == None:
                            ret[region] = {}
                        lb_name = awslib._active_balancer(dnsname, region)

                        if ret[region].get('all_ips') == None:
                            ret[region]['all_ips'] = []

                        if not eip_check == None:
                            eips = awslib._list_eips(region, filter=exclusions)
                            if verbose:
                                if ret[region].get('eips') == None:
                                    ret[region]['eips'] = eips
                                else:
                                    ret[region]['eips'].extend(eips)

                            if eip_check:
                                ret[region]['all_ips'].extend(eips)

                        if not lb_check == None:
                            lb_url = awslib._environment_descr(bs_app, lb_name, region)
                            elb = awslib._balancer_ip(lb_url)

                            if verbose:
                                if ret[region].get('elb') == None:
                                    ret[region]['elb'] = elb
                                else:
                                    ret[region]['elb'].extend(elb)

                            if lb_check:
                                ret[region]['all_ips'].extend(elb)

                        if not inst_check == None:
                            inst_ips = awslib._instance_ip(lb_name, region)
                            if verbose:
                                if ret[region].get('instance_ips') == None:
                                    ret[region]['instance_ips'] = inst_ips
                                else:
                                    ret[region]['instance_ips'].extend(inst_ips)

                            if inst_check:
                                ret[region]['all_ips'].extend(inst_ips)

            if not ret:
                return redirect(url_for('handle_index'), code=302)
            else:
                #sort ip list in ret when it can
                ret = ip_list_sort(ret)
                _write_cache(app_cache_file,ret)
        except:
            print ("Error: Unable to load new information for app: " + str(appname))
            traceback.print_exc()

    with open(app_cache_file, "r") as cache:
        # read the first line as cache time
        cache_time = cache.readline()
        line = cache.readline()
        print(line)

    return jsonify(**eval(line))

def ip_list_sort(ret):
    """
    sort ips in the nested dict list
    :param ret:
    :return:
    """
    for region in ret:
        for ip_list in ret[region]:
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
