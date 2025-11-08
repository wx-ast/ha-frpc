#!/usr/bin/env python3
"""
FRPC runner script for Home Assistant addon.
Replaces bashio-based bash script with Python implementation.
"""

import os
import shutil
import signal
import subprocess
import sys

try:
    import bashio
except ImportError:
    # Fallback for local testing
    class BashioMock:
        class Log:
            @staticmethod
            def info(msg):
                print(f'[INFO] {msg}')

        class Config:
            @staticmethod
            def require(key):
                val = os.environ.get(key.upper().replace('/', '_'))
                if not val:
                    raise ValueError(f"Required config key '{key}' not found")
                return val

            @staticmethod
            def __call__(key):
                return os.environ.get(key.upper().replace('/', '_'), '')

            @staticmethod
            def true(key):
                val = os.environ.get(key.upper().replace('/', '_'), 'false')
                return val.lower() in ('true', '1', 'yes')

        log = Log()
        config = Config()

    bashio = BashioMock()


CONFIG_SRC = '/defaults/frpc_template.toml'
PROXY_TEMPLATE_SRC = '/defaults/proxy_template.toml'
CONFIG_DST = '/data/frpc.toml'

# Global process IDs for cleanup
FRPC_PID = None
TAIL_PID = None


def signal_handler(signum, frame):
    """Handle SIGTERM and SIGHUP signals for graceful shutdown."""
    bashio.log.info('Shutting down FRPC...')
    if FRPC_PID:
        try:
            os.kill(FRPC_PID, signal.SIGTERM)
        except ProcessLookupError:
            pass
    if TAIL_PID:
        try:
            os.kill(TAIL_PID, signal.SIGTERM)
        except ProcessLookupError:
            pass
    sys.exit(0)


def replace_in_file(filepath, old, new):
    """Replace string in file."""
    with open(filepath, 'r') as f:
        content = f.read()
    content = content.replace(old, new)
    with open(filepath, 'w') as f:
        f.write(content)


def replace_line_in_file(filepath, pattern, replacement):
    """Replace line containing pattern with replacement line."""
    with open(filepath, 'r') as f:
        lines = f.readlines()

    new_lines = []
    for line in lines:
        if pattern in line:
            new_lines.append(replacement + '\n')
        else:
            new_lines.append(line)

    with open(filepath, 'w') as f:
        f.writelines(new_lines)


def delete_line_in_file(filepath, pattern):
    """Delete lines containing pattern."""
    with open(filepath, 'r') as f:
        lines = f.readlines()

    new_lines = [line for line in lines if pattern not in line]

    with open(filepath, 'w') as f:
        f.writelines(new_lines)


def generate_proxy_config(proxy_template_src, proxy_index, bashio_instance):
    """
    Generate proxy configuration from template.

    Args:
        proxy_template_src: Path to proxy template file
        proxy_index: Index of proxy in config (e.g., 0 for first proxy)
        bashio_instance: bashio instance to use

    Returns:
        str: Generated proxy configuration as string
    """
    # Read proxy template
    with open(proxy_template_src, 'r') as f:
        proxy_content = f.read()

    # Get proxy configuration values
    bashio_instance.config.require(f'proxies/{proxy_index}/name')
    proxy_keys = ['name', 'type', 'localIP', 'localPort', 'remotePort', 'useEncryption', 'useCompression']

    # Replace placeholders
    for key in proxy_keys:
        val = bashio_instance.config(f'proxies/{proxy_index}/{key}')
        placeholder = f'__{key.upper()}__'
        proxy_content = proxy_content.replace(placeholder, str(val))

    # Custom domains (optional)
    domain = bashio_instance.config(f'proxies/{proxy_index}/customDomains/0')
    if domain:
        proxy_content = proxy_content.replace('__CUSTOMDOMAINS__', f'"{domain}"')
    else:
        # Remove customDomains line if not specified
        lines = proxy_content.split('\n')
        new_lines = [line for line in lines if '__CUSTOMDOMAINS__' not in line]
        proxy_content = '\n'.join(new_lines)

    return proxy_content


def append_to_file(filepath, content):
    """Append content to file."""
    with open(filepath, 'a') as f:
        f.write('\n' + content)


def generate_config(config_src, config_dst, bashio_instance=None):
    """
    Generate FRPC configuration from template.

    Args:
        config_src: Path to template file
        config_dst: Path to output configuration file
        bashio_instance: bashio instance to use (defaults to global bashio)

    Returns:
        None (writes to config_dst file)
    """
    if bashio_instance is None:
        bashio_instance = bashio

    # Copy template to destination
    shutil.copy2(config_src, config_dst)

    # Fill in global settings
    server_addr = bashio_instance.config.require('serverAddr')
    replace_in_file(config_dst, '__SERVERADDR__', server_addr)

    server_port = bashio_instance.config.require('serverPort')
    replace_in_file(config_dst, '__SERVERPORT__', server_port)

    auth_method = bashio_instance.config.require('authMethod')
    replace_in_file(config_dst, '__AUTHMETHOD__', auth_method)

    auth_token = bashio_instance.config.require('authToken')
    replace_line_in_file(config_dst, '__AUTHTOKEN_LINE__', f'auth.token = "{auth_token}"')

    # TLS settings
    if bashio_instance.config.true('tlsEnable'):
        replace_in_file(config_dst, '__TLSENABLE__', 'true')

        tls_cert_file = bashio_instance.config('tlsCertFile')
        replace_line_in_file(config_dst, '__TLSCERT_LINE__', f'\ttls.certFile = "{tls_cert_file}"')

        tls_key_file = bashio_instance.config('tlsKeyFile')
        replace_line_in_file(config_dst, '__TLSKEY_LINE__', f'\ttls.keyFile = "{tls_key_file}"')

        tls_ca_file = bashio_instance.config('tlsCaFile')
        replace_line_in_file(config_dst, '__TLSCA_LINE__', f'\ttls.trustedCaFile = "{tls_ca_file}"')
    else:
        replace_in_file(config_dst, '__TLSENABLE__', 'false')
        delete_line_in_file(config_dst, '__TLSCERT_LINE__')
        delete_line_in_file(config_dst, '__TLSKEY_LINE__')
        delete_line_in_file(config_dst, '__TLSCA_LINE__')

    # Generate proxy configurations from separate template
    proxy_template_path = os.path.join(os.path.dirname(config_src), 'proxy_template.toml')
    proxy_index = 0
    try:
        while True:
            # Try to get proxy name - if it doesn't exist, stop
            bashio_instance.config.require(f'proxies/{proxy_index}/name')
            proxy_config = generate_proxy_config(proxy_template_path, proxy_index, bashio_instance)
            append_to_file(config_dst, proxy_config)
            proxy_index += 1
    except ValueError:
        # No more proxies found, continue
        pass


def main():
    global FRPC_PID, TAIL_PID

    try:
        # Set up signal handlers
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGHUP, signal_handler)

        bashio.log.info('Preparing configuration...')
        generate_config(CONFIG_SRC, CONFIG_DST)

        bashio.log.info('Configuration:')
        with open(CONFIG_DST, 'r') as f:
            print(f.read())

        bashio.log.info('Starting FRPC client...')
        frpc_process = subprocess.Popen(['/usr/bin/frpc', '-c', CONFIG_DST])
        FRPC_PID = frpc_process.pid

        bashio.log.info('Tailing logs...')
        tail_process = subprocess.Popen(['tail', '-F', '/share/frpc.log'])
        TAIL_PID = tail_process.pid

        # Wait for FRPC process to finish
        frpc_process.wait()
    except KeyboardInterrupt:
        signal_handler(signal.SIGTERM, None)
    except Exception as e:
        bashio.log.info(f'Error: {e}')
        signal_handler(signal.SIGTERM, None)
        sys.exit(1)


if __name__ == '__main__':
    main()
