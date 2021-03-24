# aws-ip-list-service 
Service to list IP addresses behind URLS (Route 53 Records) in AWS.

## Algorithm

Query R53 for the given `dnsname` to determine the load balancer.
Query the load balancer for the instances behind it. This should
work for AWS Elastic Beanstalk applications, as well as any other
AWS application fronted by an AWS elastic load balancer. Note that
this solution handles the case of an NLB/ALB pair (Used for effectively
supporting static IPs for application load balancers. See
[here](https://aws.amazon.com/blogs/networking-and-content-delivery/using-static-ip-addresses-for-application-load-balancers/)
for more details.)

## Config File
The config uses the following format (JSON also supported):
````
apps:
  - name: app_name
    hidden: true
    additionalText: this shows up beside the app name
    altname: alt_name
    config:
      - dnsname: example.com
        region: us-west-1
        exclusions: []
        inclusions:
          dns_list:
            - example-2.com
          ip_list: []
        show_eip: true
        show_lb_ip: true
        show_inst_ip: true
}
````

**apps:** An array of apps.   
**name:** This is the name the browser will need to point to in order to access this app's IP list.
**[hidden:]** This is an *optional* parameter the user can specify to create a hidden link.
**[altname:]** This is an *optional* parameter that the user can use to create a optional url webpage with same info (for backward compatibility purpose).
**[additionalText:]** This is an *optional* parameter that the user can use to add additional text beside the app name.
**config:** An array of variables needed.   
**dnsname:** The domain name.   
**exclusions:** List of IPs to be excluded from the result.   
**[inclusions]:** This is an optional dictionary with elements to query for IPs.   
**[dns_list]:** This is an optional list of domains to query for IPs.
**[ip_list]:** This is an optional list of IPs to include.   
**show_eip:** Whether or not to show the list of Elastic IPs associated with your account.   
**show_lb_ip:** Whether or not to show the IPs associated with the load balancer.   
**show_inst_up:** Whether or not to show the IPs of the currently running instances.
**[lb_names]:** If the dnsname above resolves directly to IP(s), supply the load balancer name(s) if show_inst_ip is set to true

An example URL would be: localhost:5000/app .   
The URL can take up to 2 query strings, verbose and region.    
verbose: Additionaly categorizes the list of IPs when verbose=1 .   
region: Only outputs information for a selected region in the config in the list of all apps .     

For the "show_eip", "show_lb_ip", "show_inst_ip" variables, the way it is processed is as follows:    
If the value is true: Show the IPs of the category in the result, and in verbose mode, list it in its own category .   
If the value is false: Do not show the IPs of the category in the result, and in verbose mode, list it in its own category .   
If the key is missing: Do not show the IPs of the category in the result, and in verbose mode, do not list it in its own category .   

## Variables

IPLIST_CONFIG_BUCKET = Name of your S3 bucket where the config file is located .   

IPLIST_CONFIG_PATH = The relative path to the config.json file .   

If you are not using S3 to hold the config file, IPLIST_CONFIG_PATH will be used to find the file locally.    

PYTHONUNBUFFERED = Force stdout to be totally unbuffered .   

The following will be needed to connect to AWS using boto .   
AWS_ACCESS_KEY_ID: Your AWS access key ID .   
AWS_SECRET_ACCESS_KEY: Your AWS secret key .   

Alternatively, boto can use a .boto file located in your home directory .   

These variables will be required if running outside of AWS.   

If running on an EC2 instance, IAM roles should be used.   

## Sample Docker Run

````
docker run -e IPLIST_CONFIG_BUCKET=S3-Bucket -e IPLIST_CONFIG_PATH="path/to/config.json" \
-e AWS_ACCESS_KEY_ID=YOUR_ACCESS_KEY -e AWS_SECRET_ACCESS_KEY=YOUR_SECRET_KEY \
-e PYTHONUNBUFFERED=1 -p 5000:5000 -d --name container-name
````

Make sure to set NOHTTPS to true if there ais no local https support when testing locally. 
```
-e NOHTTPS=True
```

