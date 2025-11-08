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

import json


# Simple config reader that reads directly from options.json
class ConfigReader:
    """Read configuration directly from /data/options.json."""

    def __init__(self, options_file='/data/options.json'):
        self.options_file = options_file
        self._options = None
        self._load_options()

    def _load_options(self):
        """Load options from JSON file."""
        if os.path.exists(self.options_file):
            try:
                with open(self.options_file, 'r') as f:
                    self._options = json.load(f)
            except Exception as e:
                self._options = {}
        else:
            self._options = {}

    def _get_value(self, key, default=None):
        """Get value from options with support for nested keys like 'proxies/0/name'."""
        if not self._options:
            return default

        if '/' in key:
            parts = key.split('/')
            val = self._options
            for part in parts:
                if part.isdigit():
                    if isinstance(val, list) and int(part) < len(val):
                        val = val[int(part)]
                    else:
                        return default
                else:
                    if isinstance(val, dict):
                        val = val.get(part)
                    else:
                        return default
                if val is None:
                    return default
            return val
        else:
            return self._options.get(key, default)

    def require(self, key):
        """Get required config value, raise error if not found."""
        val = self._get_value(key)
        if val is None or val == '' or val == []:
            raise ValueError(f"Required config key '{key}' not found")
        return val

    def __call__(self, key, default=''):
        """Get optional config value."""
        val = self._get_value(key)
        return val if (val is not None and val != '' and val != []) else default

    def true(self, key):
        """Check if config value is true."""
        val = self._get_value(key)
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in ('true', '1', 'yes')
        return bool(val)


# Try to use bashio.log if available, otherwise use print
try:
    import bashio

    log = bashio.log
except ImportError:

    class Log:
        @staticmethod
        def info(msg):
            print(f'[INFO] {msg}')

    log = Log()

# Create config instance
config = ConfigReader()


# Create bashio-like interface for compatibility
class BashioCompat:
    def __init__(self):
        self.log = log
        self.config = config


bashio = BashioCompat()


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
    # Convert new to string in case it's a number or other type
    content = content.replace(old, str(new))
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
    proxy_type = bashio_instance.config(f'proxies/{proxy_index}/type', '').lower()

    # For HTTP/HTTPS proxies, remotePort is not used (use customDomains/subdomain instead)
    # For TCP/UDP proxies, remotePort is required
    # Remove remotePort line BEFORE replacing placeholders for HTTP/HTTPS proxies
    if proxy_type in ('http', 'https'):
        lines = proxy_content.split('\n')
        new_lines = [line for line in lines if 'remotePort' not in line]
        proxy_content = '\n'.join(new_lines)

    proxy_keys = ['name', 'type', 'localIP', 'localPort', 'useEncryption', 'useCompression']
    if proxy_type not in ('http', 'https'):
        proxy_keys.append('remotePort')

    # Replace placeholders
    for key in proxy_keys:
        val = bashio_instance.config(f'proxies/{proxy_index}/{key}')
        placeholder = f'__{key.upper()}__'
        # Convert value to string, handling booleans specially
        if isinstance(val, bool):
            val_str = 'true' if val else 'false'
        else:
            val_str = str(val)
        proxy_content = proxy_content.replace(placeholder, val_str)

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
    # Remove old auth.token line with placeholder if it exists
    delete_line_in_file(config_dst, '__AUTHTOKEN__')

    # TLS settings (only add TLS config if enabled)
    if bashio_instance.config.true('tlsEnable'):
        tls_cert_file = bashio_instance.config('tlsCertFile')
        if tls_cert_file:
            replace_line_in_file(config_dst, '__TLSCERT_LINE__', f'\ttls.certFile = "{tls_cert_file}"')

        tls_key_file = bashio_instance.config('tlsKeyFile')
        if tls_key_file:
            replace_line_in_file(config_dst, '__TLSKEY_LINE__', f'\ttls.keyFile = "{tls_key_file}"')

        tls_ca_file = bashio_instance.config('tlsCaFile')
        if tls_ca_file:
            replace_line_in_file(config_dst, '__TLSCA_LINE__', f'\ttls.trustedCaFile = "{tls_ca_file}"')

    # Remove TLS placeholder lines if TLS is disabled or not configured
    if not bashio_instance.config.true('tlsEnable'):
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
        # Ensure log file exists before tailing
        log_file = '/share/frpc.log'
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        if not os.path.exists(log_file):
            open(log_file, 'a').close()

        # Start FRPC with stderr redirected to log file
        with open(log_file, 'a') as log_f:
            frpc_process = subprocess.Popen(['/usr/bin/frpc', '-c', CONFIG_DST], stdout=log_f, stderr=subprocess.STDOUT)
        FRPC_PID = frpc_process.pid

        bashio.log.info('Tailing logs...')
        # Use tail with retry option or check if file exists
        tail_process = subprocess.Popen(['tail', '-F', log_file])
        TAIL_PID = tail_process.pid

        # Wait for FRPC process to finish
        return_code = frpc_process.wait()
        if return_code != 0:
            bashio.log.info(f'FRPC exited with code {return_code}')
            # Read last lines from log file for debugging
            try:
                with open(log_file, 'r') as f:
                    lines = f.readlines()
                    if lines:
                        bashio.log.info('Last log lines:')
                        for line in lines[-10:]:
                            bashio.log.info(line.strip())
            except Exception:
                pass
            sys.exit(return_code)
    except KeyboardInterrupt:
        signal_handler(signal.SIGTERM, None)
    except Exception as e:
        bashio.log.info(f'Error: {e}')
        signal_handler(signal.SIGTERM, None)
        sys.exit(1)


if __name__ == '__main__':
    main()
