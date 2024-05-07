# NVIDIA GPU Monitoring Server

Welcome to the NVIDIA GPU Monitoring Server! This server is designed to work with NVIDIA GPUs and provides a RESTful API to monitor various GPU parameters in real-time.

## Features

- Real-time monitoring of GPU parameters.
- Easy integration with Home Assistant.
- RESTful API for easy access and compatibility.

## API Endpoints

The server provides the following endpoints, each returning a specific GPU parameter:

- `/powerusage`: Current power usage in watts.
- `/temperature`: Current temperature in degrees Celsius.
- `/fanspeed`: Current fan speed as a percentage of its maximum speed.
- `/memoryusage`: Current memory usage in MiB.
- `/gpuutil`: Current GPU utilization as a percentage.

## Configuration

Before starting the application, ensure you edit your configuration file `nvidia-endpoint-server.conf`. The configuration file should be located in the same directory as the script. Here's an example of what the configuration file should look like:

```conf
[DEFAULT]
HOST = 127.0.0.1
PORT = 5000
USE_HTTPS = False
CERTIFICATE_PATH = /path/to/your/certificate.crt
KEY_PATH = /path/to/your/key.key
```


## Docker Container

This docker container uses the Official Docker image from NVIDIA and has python installed. 
Before starting the container you can edit the docker-compose.yaml and change the exposed ports.

Startiong container: 
```docker compose up -d ```



## Home Assistant Integration

This server can be integrated with Home Assistant using the RESTful sensor. Here are some examples of how to set up the sensors in your Home Assistant configuration:

```yaml
sensor:
- platform: rest
    resource: http://IP_ADDRESS:PORT/powerusage
    name: GPU Power Usage
    value_template: '{{ value_json.power_usage }}'
    unit_of_measurement: 'W'
    device_class: energy
    state_class: measurement

- platform: integration
    source: sensor.gpu_power_usage
    name: 'Example Energy Usage'
    unit_prefix: k
    unit_time: h

- platform: rest
    name: GPU Temperature
    resource: http://IP_ADDRESS:PORT/temperature
    value_template: '{{ value_json.temperature }}'
    unit_of_measurement: '°C'

- platform: rest
    name: GPU Fan Speed
    resource: http://IP_ADDRESS:PORT/fanspeed
    value_template: '{{ value_json.fan_speed }}'
    unit_of_measurement: '%'

- platform: rest
    name: GPU Memory Usage
    resource: http://IP_ADDRESS:PORT/memoryusage
    value_template: '{{ value_json.memory_usage }}'
    unit_of_measurement: 'MiB'

- platform: rest
    name: GPU Utilization
    resource: http://IP_ADDRESS:PORT/gpuutil
    value_template: '{{ value_json.gpu_util }}'
    unit_of_measurement: '%'
```

Please replace `IP_ADDRESS` and `PORT` with the actual IP address and port of your server.


## Support

If you find these lists useful, please consider giving me a star on GitHub!
