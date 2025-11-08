#!/usr/bin/env python3
"""
Tests for FRPC configuration generation.
"""

import os
import tempfile
from pathlib import Path

import pytest

from run import generate_config


class MockBashio:
    """Mock bashio for testing."""

    class Log:
        @staticmethod
        def info(msg):
            pass

    class Config:
        def __init__(self, config_dict):
            self._config = config_dict

        def _get_nested_value(self, key):
            """Get value from nested config dict (supports 'proxies/0/name' format)."""
            if '/' in key:
                parts = key.split('/')
                val = self._config
                for part in parts:
                    if part.isdigit():
                        if isinstance(val, list) and int(part) < len(val):
                            val = val[int(part)]
                        else:
                            return None
                    else:
                        if isinstance(val, dict):
                            val = val.get(part)
                        else:
                            return None
                    if val is None:
                        return None
                return val
            else:
                return self._config.get(key)

        def _get_value(self, key, default=None):
            """Get value from config (compatible with ConfigReader._get_value)."""
            val = self._get_nested_value(key)
            return val if val is not None else default

        def require(self, key):
            val = self._get_nested_value(key)
            if val is None or val == '' or val == []:
                raise ValueError(f"Required config key '{key}' not found")
            return val

        def __call__(self, key, default=''):
            val = self._get_nested_value(key)
            return val if (val is not None and val != '' and val != []) else default

        def true(self, key):
            val = self._get_nested_value(key)
            if isinstance(val, bool):
                return val
            if isinstance(val, str):
                return val.lower() in ('true', '1', 'yes')
            return bool(val)

    def __init__(self, config_dict):
        self.log = self.Log()
        self.config = self.Config(config_dict)


@pytest.fixture
def template_path():
    """Get path to template file."""
    path = Path(__file__).parent / 'defaults' / 'frpc_template.toml'
    assert path.exists(), f'Template not found at {path}'
    return path


@pytest.fixture
def temp_config_file():
    """Create temporary config file."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.toml') as tmp_file:
        output_path = tmp_file.name
    yield output_path
    # Cleanup
    if os.path.exists(output_path):
        os.unlink(output_path)


def test_proxy_config_without_custom_domains(template_path, temp_config_file):
    """Test proxy configuration generation without customDomains."""
    # Test configuration with nested structure
    config_dict = {
        'serverAddr': 'example.com',
        'serverPort': 7000,  # Integer type
        'authMethod': 'token',
        'authToken': 'test-token',
        'tlsEnable': False,  # Boolean type
        'proxies': [
            {
                'name': 'pi4.vlcam',
                'type': 'tcp',
                'localIP': '192.168.2.50',
                'localPort': 34567,  # Integer type
                'remotePort': 54567,  # Integer type
                'useEncryption': True,  # Boolean type
                'useCompression': True,  # Boolean type
                'customDomains': [],  # Empty - should be removed
            }
        ],
    }

    mock_bashio = MockBashio(config_dict)

    # Generate configuration
    generate_config(str(template_path), temp_config_file, mock_bashio)

    # Read generated configuration
    with open(temp_config_file, 'r') as f:
        config_content = f.read()

    # Check that proxy section exists with correct values
    assert '[[proxies]]' in config_content
    assert 'name = "pi4.vlcam"' in config_content
    assert 'type = "tcp"' in config_content
    assert 'localIP = "192.168.2.50"' in config_content
    assert 'localPort = 34567' in config_content
    assert 'remotePort = 54567' in config_content
    assert 'transport.useEncryption = true' in config_content
    assert 'transport.useCompression = true' in config_content

    # Check that customDomains line is removed
    assert 'customDomains' not in config_content

    # Verify the exact proxy section format
    lines = config_content.split('\n')
    proxy_section_started = False
    proxy_lines = []
    for line in lines:
        if '[[proxies]]' in line:
            proxy_section_started = True
            continue
        if proxy_section_started:
            if line.strip() and not line.strip().startswith('['):
                proxy_lines.append(line.strip())
            elif line.strip().startswith('['):
                break

    # Check that all required fields are present in proxy section
    proxy_content = '\n'.join(proxy_lines)
    assert 'name = "pi4.vlcam"' in proxy_content
    assert 'type = "tcp"' in proxy_content
    assert 'localIP = "192.168.2.50"' in proxy_content
    assert 'localPort = 34567' in proxy_content
    assert 'remotePort = 54567' in proxy_content
    assert 'transport.useEncryption = true' in proxy_content
    assert 'transport.useCompression = true' in proxy_content
    assert 'customDomains' not in proxy_content


def test_proxy_config_with_custom_domains(template_path, temp_config_file):
    """Test proxy configuration generation with customDomains."""
    # Test configuration with nested structure
    config_dict = {
        'serverAddr': 'example.com',
        'serverPort': 7000,  # Integer type
        'authMethod': 'token',
        'authToken': 'test-token',
        'tlsEnable': False,  # Boolean type
        'proxies': [
            {
                'name': 'web',
                'type': 'https',
                'localIP': '192.168.2.65',
                'localPort': 8123,  # Integer type
                'useEncryption': True,  # Boolean type
                'useCompression': True,  # Boolean type
                'customDomains': ['fvl.atyx.ru'],
            }
        ],
    }

    mock_bashio = MockBashio(config_dict)

    # Generate configuration
    generate_config(str(template_path), temp_config_file, mock_bashio)

    # Read generated configuration
    with open(temp_config_file, 'r') as f:
        config_content = f.read()

    # Check that proxy section exists with correct values
    assert '[[proxies]]' in config_content
    assert 'name = "web"' in config_content
    assert 'type = "https"' in config_content
    assert 'localIP = "192.168.2.65"' in config_content
    assert 'localPort = 8123' in config_content
    assert 'customDomains = ["fvl.atyx.ru"]' in config_content
    # For HTTPS proxy, remotePort should NOT be present
    assert 'remotePort' not in config_content

    # Verify the exact proxy section format
    lines = config_content.split('\n')
    proxy_section_started = False
    proxy_lines = []
    for line in lines:
        if '[[proxies]]' in line:
            proxy_section_started = True
            continue
        if proxy_section_started:
            if line.strip() and not line.strip().startswith('['):
                proxy_lines.append(line.strip())
            elif line.strip().startswith('['):
                break

    # Check that all required fields are present in proxy section
    proxy_content = '\n'.join(proxy_lines)
    assert 'name = "web"' in proxy_content
    assert 'type = "https"' in proxy_content
    assert 'localIP = "192.168.2.65"' in proxy_content
    assert 'localPort = 8123' in proxy_content
    assert 'customDomains = ["fvl.atyx.ru"]' in proxy_content
    assert 'remotePort' not in proxy_content


def test_type_conversion(temp_config_file):
    """Test that numeric and boolean types are correctly converted to strings."""
    from run import replace_in_file

    # Create a temporary file with placeholder
    with open(temp_config_file, 'w') as f:
        f.write('serverAddr = __SERVERADDR__\n')
        f.write('serverPort = __SERVERPORT__\n')

    # Test integer conversion
    replace_in_file(temp_config_file, '__SERVERPORT__', 7000)

    # Test string conversion
    replace_in_file(temp_config_file, '__SERVERADDR__', 'example.com')

    # Read result
    with open(temp_config_file, 'r') as f:
        content = f.read()

    # Verify conversions
    assert 'serverPort = 7000' in content
    assert 'serverAddr = example.com' in content


def test_proxy_config_type_conversion(template_path, temp_config_file):
    """Test that proxy configuration correctly converts types (int, bool) to strings."""
    # Test configuration with various types
    config_dict = {
        'serverAddr': 'test.example.com',
        'serverPort': 7000,  # Integer
        'authMethod': 'token',
        'authToken': 'secret-token',
        'tlsEnable': True,  # Boolean
        'proxies': [
            {
                'name': 'test-proxy',
                'type': 'tcp',
                'localIP': '127.0.0.1',
                'localPort': 8080,  # Integer
                'remotePort': 9090,  # Integer
                'useEncryption': False,  # Boolean - should become 'false'
                'useCompression': True,  # Boolean - should become 'true'
            }
        ],
    }

    mock_bashio = MockBashio(config_dict)

    # Generate configuration
    generate_config(str(template_path), temp_config_file, mock_bashio)

    # Read generated configuration
    with open(temp_config_file, 'r') as f:
        config_content = f.read()

    # Check that integer values are correctly converted
    assert 'serverPort = 7000' in config_content or 'serverPort = "7000"' in config_content
    assert 'localPort = 8080' in config_content or 'localPort = "8080"' in config_content
    assert 'remotePort = 9090' in config_content or 'remotePort = "9090"' in config_content

    # Check that boolean values are correctly converted to lowercase 'true'/'false'
    assert 'transport.useEncryption = false' in config_content
    assert 'transport.useCompression = true' in config_content

    # Verify no Python-style booleans (True/False) are present
    assert 'useEncryption = False' not in config_content
    assert 'useEncryption = True' not in config_content
    assert 'useCompression = False' not in config_content
    assert 'useCompression = True' not in config_content

    # Verify tlsEnable is not in config (removed from template)
    assert 'tlsEnable' not in config_content


def test_https_proxy_without_custom_domains_uses_subdomain(template_path, temp_config_file):
    """Test that HTTPS proxy without customDomains and subdomain raises error."""
    config_dict = {
        'serverAddr': 'example.com',
        'serverPort': 7000,
        'authMethod': 'token',
        'authToken': 'test-token',
        'tlsEnable': False,
        'proxies': [
            {
                'name': 'web',
                'type': 'https',
                'localIP': '127.0.0.1',
                'localPort': 8123,
                'useEncryption': False,
                'useCompression': False,
            }
        ],
    }

    mock_bashio = MockBashio(config_dict)

    # Should raise ValueError because neither subdomain nor customDomains is specified
    with pytest.raises(ValueError, match='requires either "subdomain" or "customDomains"'):
        generate_config(str(template_path), temp_config_file, mock_bashio)


def test_https_proxy_with_custom_domains_only(template_path, temp_config_file):
    """Test HTTPS proxy with only customDomains (no subdomain)."""
    config_dict = {
        'serverAddr': 'example.com',
        'serverPort': 7000,
        'authMethod': 'token',
        'authToken': 'test-token',
        'tlsEnable': False,
        'proxies': [
            {
                'name': 'web',
                'type': 'https',
                'localIP': '127.0.0.1',
                'localPort': 8123,
                'customDomains': ['home.example.com'],
                'useEncryption': False,
                'useCompression': False,
            }
        ],
    }

    mock_bashio = MockBashio(config_dict)
    generate_config(str(template_path), temp_config_file, mock_bashio)

    with open(temp_config_file, 'r') as f:
        config_content = f.read()

    # Should have customDomains but not subdomain
    assert 'customDomains = ["home.example.com"]' in config_content
    assert 'subdomain' not in config_content
    assert 'remotePort' not in config_content


def test_https_proxy_with_subdomain(template_path, temp_config_file):
    """Test HTTPS proxy with explicit subdomain."""
    config_dict = {
        'serverAddr': 'example.com',
        'serverPort': 7000,
        'authMethod': 'token',
        'authToken': 'test-token',
        'tlsEnable': False,
        'proxies': [
            {
                'name': 'web',
                'type': 'https',
                'localIP': '127.0.0.1',
                'localPort': 8123,
                'subdomain': 'homeassistant',
                'useEncryption': False,
                'useCompression': False,
            }
        ],
    }

    mock_bashio = MockBashio(config_dict)
    generate_config(str(template_path), temp_config_file, mock_bashio)

    with open(temp_config_file, 'r') as f:
        config_content = f.read()

    assert 'subdomain = "homeassistant"' in config_content
    assert 'remotePort' not in config_content


def test_http_proxy_with_both_subdomain_and_custom_domains(template_path, temp_config_file):
    """Test HTTP proxy with both subdomain and customDomains."""
    config_dict = {
        'serverAddr': 'example.com',
        'serverPort': 7000,
        'authMethod': 'token',
        'authToken': 'test-token',
        'tlsEnable': False,
        'proxies': [
            {
                'name': 'web',
                'type': 'http',
                'localIP': '127.0.0.1',
                'localPort': 8123,
                'subdomain': 'home',
                'customDomains': ['home.example.com'],
                'useEncryption': False,
                'useCompression': False,
            }
        ],
    }

    mock_bashio = MockBashio(config_dict)
    generate_config(str(template_path), temp_config_file, mock_bashio)

    with open(temp_config_file, 'r') as f:
        config_content = f.read()

    assert 'subdomain = "home"' in config_content
    assert 'customDomains = ["home.example.com"]' in config_content
    assert 'remotePort' not in config_content
