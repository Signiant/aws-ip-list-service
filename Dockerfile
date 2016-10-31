FROM python:2-onbuild

VOLUME /ip-range-cache

EXPOSE 80

CMD [ "python", "./aws-ip-list-service.py" ]
