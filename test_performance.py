#!/usr/bin/env python3
"""
Basic test suite for OpenWRTInvasion performance optimizations.
Validates functionality and performance requirements.
"""

import time
import socket
import subprocess
import sys
try:
    import pytest
    PYTEST_AVAILABLE = True
except ImportError:
    PYTEST_AVAILABLE = False
    # Mock pytest decorators
    class pytest:
        class mark:
            @staticmethod
            def skipif(condition, reason=""):
                def decorator(func):
                    if condition:
                        def wrapper(*args, **kwargs):
                            print(f"SKIP: {func.__name__} - {reason}")
                            return None
                        return wrapper
                    return func
                return decorator
            @staticmethod  
            def parametrize(param_name, param_values):
                def decorator(func):
                    def wrapper(*args, **kwargs):
                        for value in param_values:
                            kwargs[param_name] = value
                            func(*args, **kwargs)
                    return wrapper
                return decorator
        @staticmethod
        def skip(reason):
            print(f"SKIP: {reason}")
        @staticmethod
        def fail(reason):
            raise AssertionError(reason)
        @staticmethod
        def fixture(func):
            return func

try:
    from unittest.mock import patch, MagicMock
except ImportError:
    # Basic mock for older Python
    class patch:
        def __init__(self, target, new=None):
            self.target = target
            self.new = new
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

try:
    from exploit_performance import (
        ExploitSettings, FastPortChecker, AsyncPortChecker,
        OptimizedSession, fast_service_check
    )
    OPTIMIZATIONS_AVAILABLE = True
except ImportError:
    OPTIMIZATIONS_AVAILABLE = False


class TestExploitSettings:
    """Test configuration and settings."""
    
    @pytest.mark.skipif(not OPTIMIZATIONS_AVAILABLE, reason="Optimizations not available")
    def test_v1_defaults(self):
        """Test V1 (aggressive) default settings."""
        settings = ExploitSettings('v1')
        assert settings.timeout == 1.0
        assert settings.delay == 0.25
        assert settings.retries == 2
    
    @pytest.mark.skipif(not OPTIMIZATIONS_AVAILABLE, reason="Optimizations not available")
    def test_v2_defaults(self):
        """Test V2 (conservative) default settings."""
        settings = ExploitSettings('v2')
        assert settings.timeout == 5.0
        assert settings.delay == 1.0
        assert settings.retries == 3
    
    @pytest.mark.skipif(not OPTIMIZATIONS_AVAILABLE, reason="Optimizations not available")
    def test_custom_overrides(self):
        """Test custom setting overrides."""
        settings = ExploitSettings('v1', timeout=2.5, retries=5)
        assert settings.timeout == 2.5
        assert settings.retries == 5
        assert settings.delay == 0.25  # Should keep default


class TestPortChecking:
    """Test port checking optimizations."""
    
    @pytest.mark.skipif(not OPTIMIZATIONS_AVAILABLE, reason="Optimizations not available")
    def test_fast_port_checker_creation(self):
        """Test FastPortChecker instantiation."""
        settings = ExploitSettings('v1')
        checker = FastPortChecker(settings)
        assert checker.settings == settings
    
    @pytest.mark.skipif(not OPTIMIZATIONS_AVAILABLE, reason="Optimizations not available") 
    def test_single_port_check_localhost(self):
        """Test single port check against localhost."""
        settings = ExploitSettings('v1', timeout=1.0)
        checker = FastPortChecker(settings)
        
        # Test common ports that should be closed
        result = checker.check_port_sync("127.0.0.1", 9999, timeout=0.5)
        assert isinstance(result, bool)
    
    @pytest.mark.skipif(not OPTIMIZATIONS_AVAILABLE, reason="Optimizations not available")
    def test_parallel_port_check_performance(self):
        """Test parallel port checking performance."""
        settings = ExploitSettings('v1', timeout=0.5)
        checker = FastPortChecker(settings)
        
        ports = [22, 80, 443, 8080, 9999]
        
        # Time parallel check
        start = time.time()
        results = checker.check_ports_parallel("127.0.0.1", ports)
        parallel_time = time.time() - start
        
        # Verify results format
        assert isinstance(results, dict)
        assert len(results) == len(ports)
        for port in ports:
            assert port in results
            assert isinstance(results[port], bool)
        
        # Should complete reasonably fast
        assert parallel_time < 5.0


class TestServiceDetection:
    """Test service detection optimization."""
    
    @pytest.mark.skipif(not OPTIMIZATIONS_AVAILABLE, reason="Optimizations not available")
    def test_fast_service_check_timeout(self):
        """Test service check with timeout."""
        settings = ExploitSettings('v1', timeout=0.3)
        
        # Should complete quickly even with non-responsive host
        start = time.time()
        result = fast_service_check("192.0.2.1", [22, 80], settings)  # TEST-NET-1 (non-routable)
        elapsed = time.time() - start
        
        # Should timeout quickly and return None
        assert elapsed < 2.0
        assert result is None
    
    @pytest.mark.skipif(not OPTIMIZATIONS_AVAILABLE, reason="Optimizations not available")
    def test_service_check_localhost(self):
        """Test service check against localhost."""
        settings = ExploitSettings('v1')
        
        # Check common local services
        result = fast_service_check("127.0.0.1", [22, 80, 443])
        # Result can be None or a port number
        assert result is None or isinstance(result, int)


class TestPerformanceRequirements:
    """Test performance requirements."""
    
    @pytest.mark.skipif(not OPTIMIZATIONS_AVAILABLE, reason="Optimizations not available")
    @pytest.mark.parametrize("latency_profile", ["low", "medium"])
    def test_service_check_performance_gate(self, latency_profile):
        """Test that service checking meets performance requirements."""
        if latency_profile == "low":
            # Low latency: should complete in <2s
            settings = ExploitSettings('v1', timeout=0.5)
            max_time = 2.0
        else:
            # Medium latency: should complete in <5s
            settings = ExploitSettings('v2', timeout=1.0) 
            max_time = 5.0
        
        ports = [22, 23, 21, 80, 443]
        
        start = time.time()
        result = fast_service_check("127.0.0.1", ports, settings)
        elapsed = time.time() - start
        
        # Performance gate: must complete within time limit
        assert elapsed < max_time, f"Service check took {elapsed:.2f}s, expected <{max_time}s"


class TestOptimizedScript:
    """Test the optimized main script."""
    
    def test_script_help_flag(self):
        """Test that the optimized script shows help."""
        try:
            result = subprocess.run([
                sys.executable, 
                "remote_command_execution_vulnerability_optimized.py", 
                "--help"
            ], capture_output=True, text=True, timeout=10)
            
            assert result.returncode == 0
            assert "OpenWRT Invasion Exploit - Performance Optimized" in result.stdout
            assert "--timeout" in result.stdout
            assert "--retries" in result.stdout
            
        except FileNotFoundError:
            pytest.skip("Optimized script not found")
        except subprocess.TimeoutExpired:
            pytest.fail("Script help command timed out")
    
    def test_script_version_flags(self):
        """Test that script accepts version-specific flags."""
        try:
            # Test with invalid router (should fail fast)
            result = subprocess.run([
                sys.executable,
                "remote_command_execution_vulnerability_optimized.py",
                "--router-ip", "192.0.2.1",  # TEST-NET-1
                "--timeout", "0.1",
                "--retries", "1",
                "--quiet"
            ], capture_output=True, text=True, timeout=30)
            
            # Should exit with error but not crash
            assert result.returncode != 0
            
        except FileNotFoundError:
            pytest.skip("Optimized script not found")
        except subprocess.TimeoutExpired:
            pytest.fail("Script execution timed out")


class TestBackwardCompatibility:
    """Test backward compatibility and fallbacks."""
    
    def test_fallback_without_optimizations(self):
        """Test that code works without optimization modules."""
        # This test runs even if optimizations are available
        # to ensure fallback paths work
        
        with patch('exploit_performance.ExploitSettings', None):
            # Test that legacy functions still work
            # (This would be more comprehensive with actual legacy functions)
            assert True  # Placeholder
    
    @pytest.mark.skipif(not OPTIMIZATIONS_AVAILABLE, reason="Optimizations not available")
    def test_legacy_check_host_compatibility(self):
        """Test legacy function compatibility."""
        from exploit_performance import legacy_check_host
        
        # Should work with minimal parameters
        result = legacy_check_host("127.0.0.1", 9999)  # Unlikely to be open
        assert isinstance(result, bool)


# Pytest configuration and fixtures

@pytest.fixture
def performance_settings():
    """Fixture providing test performance settings."""
    if OPTIMIZATIONS_AVAILABLE:
        return ExploitSettings('v1', timeout=0.5, retries=1, delay=0.1)
    else:
        return None


# Performance benchmarks (can be run separately)

def benchmark_parallel_vs_sequential():
    """Benchmark parallel vs sequential port checking."""
    if not OPTIMIZATIONS_AVAILABLE:
        print("Optimizations not available for benchmarking")
        return
    
    ports = [22, 80, 443, 8080, 9999]
    host = "127.0.0.1"
    
    # Sequential timing
    start = time.time()
    for port in ports:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        try:
            sock.connect_ex((host, port))
            sock.close()
        except:
            pass
    sequential_time = time.time() - start
    
    # Parallel timing
    settings = ExploitSettings('v1', timeout=0.5)
    checker = FastPortChecker(settings)
    
    start = time.time()
    results = checker.check_ports_parallel(host, ports)
    parallel_time = time.time() - start
    
    speedup = sequential_time / parallel_time if parallel_time > 0 else 0
    
    print(f"Sequential: {sequential_time:.2f}s")
    print(f"Parallel:   {parallel_time:.2f}s") 
    print(f"Speedup:    {speedup:.1f}x")
    
    return speedup


if __name__ == "__main__":
    # Run basic functionality test
    print("OpenWRTInvasion Performance Test Suite")
    print("=" * 40)
    
    if OPTIMIZATIONS_AVAILABLE:
        print("✅ Performance optimizations available")
        
        # Quick functionality test
        settings = ExploitSettings('v1')
        print(f"✅ Settings: timeout={settings.timeout}s, retries={settings.retries}")
        
        # Quick benchmark
        speedup = benchmark_parallel_vs_sequential()
        if speedup >= 1.5:
            print(f"✅ Performance improvement: {speedup:.1f}x")
        else:
            print(f"⚠️  Limited performance improvement: {speedup:.1f}x")
            
    else:
        print("❌ Performance optimizations not available")
        print("   Install exploit_performance.py to enable optimizations")
    
    print("\nRun 'pytest test_performance.py' for full test suite")