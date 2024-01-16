# NVIDIA Endpoint Server

This server is designed to provide various statistics about your NVIDIA GPU. It uses Flask to create a web server with multiple endpoints, each returning a specific type of data about the GPU.

## Installation

1. Clone this repository.
2. Install the required Python packages: pyOpenSSL, Flask, subprocess, re, configparser, os. 

## Configuration

The server's configuration is stored in a file named `nvidia-endpoint-server.conf`. This file should be located in the same directory as the server script. The configuration file contains the following settings:

- HOST: The hostname to use when running the server.
- PORT: The port to use when running the server.
- USE_HTTPS: A boolean value indicating whether to use HTTPS.
- CERT_PATH: The path to the SSL certificate file (required if USE_HTTPS is True).
- KEY_PATH: The path to the SSL key file (required if USE_HTTPS is True).

## Endpoints

The server provides the following endpoints:

- `/powerusage`: Returns the power usage of the GPU.
- `/temperature`: Returns the temperature of the GPU.
- `/fanspeed`: Returns the fan speed of the GPU.
- `/memoryusage`: Returns the memory usage of the GPU.
- `/gpuutil`: Returns the GPU utilization.

## Running the Server

To run the server, execute the script with Python. The server will start and print out the available endpoints. Depending on the configuration, the server may run with or without SSL.

## Examples for Homeassistant
```
sensor:
  - platform: rest
    resource: http://IP_ADDRESS:PORT/powerusage
    name: GPU Power Usage
    value_template: '{{ value_json[0] }}'
    unit_of_measurement: 'W'
    device_class: energy
    state_class: measurement

- platform: integration
    source: sensor.gpu_power_usage
    name: 'Example Energy Usage'
    unit_prefix: k
    unit_time: h

  - platform: rest
    resource: http://IP_ADDRESS:PORT/temperature
    name: GPU Temperature
    value_template: '{{ value_json[0] }}'
    unit_of_measurement: '°C'

  - platform: rest
    resource: http://IP_ADDRESS:PORT/fanspeed
    name: GPU Fan Speed
    value_template: '{{ value_json[0] }}'
    unit_of_measurement: '%'

  - platform: rest
    resource: http://IP_ADDRESS:PORT/memoryusage
    name: GPU Memory Usage
    value_template: '{{ value_json[0] }}'
    unit_of_measurement: 'Mb'

  - platform: rest
    resource: http://IP_ADDRESS:PORT/gpuutil
    name: GPU Utilization
    value_template: '{{ value_json[0] }}'
    unit_of_measurement: '%'
```
