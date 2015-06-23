from app import app
from flask import render_template
import json
from json import dumps
from os.path import join
from flask import make_response, request, redirect
import awslib
import os


bucket_name = os.environ.get('IPLIST_CONFIG_BUCKET')
s3path = os.environ.get('IPLIST_CONFIG_PATH')
nohttps = os.environ.get('NOHTTPS')

path = join('iplist_config', 'config.json')

if s3path == None:
    print "No Env Labeled IPLIST_CONFIG_PATH"
else:
    awslib._get_config(bucket_name, s3path, path)

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
    return "I'm still here."

@app.route('/<appname>')
def handle_app(appname):
    with open(path) as json_data:
        data = json.load(json_data)

    verbose = False
    chosen_region = None
    ret = {}
    query_string = request.query_string

    if not query_string == "":
        for query in query_string.split('&'):
            if "verbose" in query.lower():
                if query.endswith("1"):
                    verbose = True
            elif "region" in query.lower():
                chosen_region = query[7:]

    if verbose:
        print request.url
    redir = None
    if nohttps == None:
        proto = request.headers.get("X-Forwarded-Proto")
        if not proto == "https":
            redir = _check_ssl(request.url, verbose)
    if not redir == None:
        return redir

    for app in data['apps']:
        if appname.lower() == app['name'].lower():
            app_config = app['config']
            for config in app_config:
                dnsname = config['dnsname']
                bs_app = config['beanstalk_app_name']
                region = config['region']

                if not chosen_region == None:
                    if not region == chosen_region:
                        continue

                exclusions = config['exclusions']
                eip_check = config.get('show_eip')
                lb_check = config.get('show_lb_ip')
                inst_check = config.get('show_inst_ip')

                ret[region] = {}
                lb_name = awslib._active_balancer(dnsname, region)                
                
                ret[region]['all_ips'] = []

                if not eip_check == None:
                    eips = awslib._list_eips(region, filter=exclusions)
                    if verbose:
                        ret[region]['eips'] = eips
                    if eip_check:
                        ret[region]['all_ips'].extend(eips)

                if not lb_check == None:
                    lb_url = awslib._environment_descr(bs_app, lb_name, region)
                    elb = awslib._balancer_ip(lb_url)

                    if verbose:
                        ret[region]['elb'] = elb
                    if lb_check:
                        ret[region]['all_ips'].extend(elb)

                if not inst_check == None:
                    inst_ips = awslib._instance_ip(lb_name, region)
                    if verbose:
                        ret[region]['instance_ips'] = inst_ips
                    if inst_check:
                        ret[region]['all_ips'].extend(inst_ips)

    if not ret:
        return "Could not load app named: " + appname
    else:    
        return jsonify(**ret)

def jsonify(status=200, indent=4, sort_keys=False, **kwargs):
    response = make_response(dumps(dict(**kwargs), indent=indent, sort_keys=sort_keys))
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    response.headers['mimetype'] = 'application/json'
    response_code = status
    return response

def _check_ssl(url, verbose=False):
    if verbose:
        print "Current scheme: %s" % url[:5]
    if url[:5] == "https":
        return None
    else:
        return redirect("https" + url[4:], code=302)
