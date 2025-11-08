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

        def require(self, key):
            if key not in self._config:
                raise ValueError(f"Required config key '{key}' not found")
            return self._config[key]

        def __call__(self, key):
            return self._config.get(key, '')

        def true(self, key):
            val = self._config.get(key, 'false')
            return str(val).lower() in ('true', '1', 'yes')

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
    # Test configuration
    config_dict = {
        'serverAddr': 'example.com',
        'serverPort': '7000',
        'authMethod': 'token',
        'authToken': 'test-token',
        'tlsEnable': 'false',
        'proxies/0/name': 'pi4.vlcam',
        'proxies/0/type': 'tcp',
        'proxies/0/localIP': '192.168.2.50',
        'proxies/0/localPort': '34567',
        'proxies/0/remotePort': '54567',
        'proxies/0/useEncryption': 'true',
        'proxies/0/useCompression': 'true',
        'proxies/0/customDomains/0': '',  # Empty - should be removed
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
    # Test configuration
    config_dict = {
        'serverAddr': 'example.com',
        'serverPort': '7000',
        'authMethod': 'token',
        'authToken': 'test-token',
        'tlsEnable': 'false',
        'proxies/0/name': 'web',
        'proxies/0/type': 'https',
        'proxies/0/localIP': '192.168.2.65',
        'proxies/0/localPort': '8123',
        'proxies/0/remotePort': '8123',  # Required field
        'proxies/0/useEncryption': 'true',  # Required field
        'proxies/0/useCompression': 'true',  # Required field
        'proxies/0/customDomains/0': 'fvl.atyx.ru',
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
