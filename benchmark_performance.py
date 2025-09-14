#!/usr/bin/env python3
"""
Benchmark script for OpenWRTInvasion performance optimizations.
Tests socket connection checking and HTTP session performance.
"""

import time
import socket
import statistics
from concurrent.futures import ThreadPoolExecutor
import asyncio

try:
    from exploit_performance import (
        ExploitSettings, FastPortChecker, AsyncPortChecker,
        OptimizedSession, fast_service_check
    )
    OPTIMIZATIONS_AVAILABLE = True
except ImportError:
    OPTIMIZATIONS_AVAILABLE = False
    print("Warning: Performance optimizations not available")

import requests


def benchmark_socket_checks():
    """Benchmark socket connection checking methods."""
    print("\n=== Socket Connection Benchmark ===")
    
    test_hosts = [
        ("127.0.0.1", [22, 80, 443, 8080]),  # Local host
        ("8.8.8.8", [53, 443]),              # Google DNS
        ("1.1.1.1", [53, 443]),              # Cloudflare DNS
    ]
    
    # Test legacy method
    print("Testing legacy sequential checking...")
    legacy_times = []
    
    for host, ports in test_hosts:
        start = time.time()
        for port in ports:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            try:
                result = sock.connect_ex((host, port))
                sock.close()
            except:
                pass
        elapsed = time.time() - start
        legacy_times.append(elapsed)
        print(f"  {host}: {elapsed:.2f}s")
    
    if OPTIMIZATIONS_AVAILABLE:
        # Test optimized parallel method
        print("\nTesting optimized parallel checking...")
        settings = ExploitSettings('v1', timeout=1.0)
        checker = FastPortChecker(settings)
        parallel_times = []
        
        for host, ports in test_hosts:
            start = time.time()
            results = checker.check_ports_parallel(host, ports)
            elapsed = time.time() - start
            parallel_times.append(elapsed)
            print(f"  {host}: {elapsed:.2f}s")
        
        # Test async method if available
        try:
            if hasattr(asyncio, 'run'):
                print("\nTesting async parallel checking...")
                async_checker = AsyncPortChecker(settings)
                async_times = []
                
                for host, ports in test_hosts:
                    async def test_host():
                        return await async_checker.check_ports_async(host, ports)
                    
                    start = time.time()
                    results = asyncio.run(test_host())
                    elapsed = time.time() - start
                    async_times.append(elapsed)
                    print(f"  {host}: {elapsed:.2f}s")
                
                print(f"\nResults:")
                print(f"Legacy avg:   {statistics.mean(legacy_times):.2f}s")
                print(f"Parallel avg: {statistics.mean(parallel_times):.2f}s")
                print(f"Async avg:    {statistics.mean(async_times):.2f}s")
                
                speedup_parallel = statistics.mean(legacy_times) / statistics.mean(parallel_times)
                speedup_async = statistics.mean(legacy_times) / statistics.mean(async_times)
                print(f"Parallel speedup: {speedup_parallel:.1f}x")
                print(f"Async speedup:    {speedup_async:.1f}x")
                
        except ImportError:
            print("Async testing not available (Python < 3.7)")
            print(f"\nResults:")
            print(f"Legacy avg:   {statistics.mean(legacy_times):.2f}s")
            print(f"Parallel avg: {statistics.mean(parallel_times):.2f}s")
            
            speedup = statistics.mean(legacy_times) / statistics.mean(parallel_times)
            print(f"Parallel speedup: {speedup:.1f}x")


def benchmark_http_sessions():
    """Benchmark HTTP session performance."""
    print("\n=== HTTP Session Benchmark ===")
    
    test_urls = [
        "http://httpbin.org/delay/0",
        "http://httpbin.org/status/200", 
        "http://httpbin.org/headers",
        "http://httpbin.org/user-agent",
    ]
    
    # Test standard requests
    print("Testing standard requests...")
    standard_times = []
    
    for url in test_urls:
        start = time.time()
        try:
            response = requests.get(url, timeout=5)
        except:
            pass
        elapsed = time.time() - start
        standard_times.append(elapsed)
        print(f"  {url}: {elapsed:.2f}s")
    
    if OPTIMIZATIONS_AVAILABLE:
        # Test optimized session
        print("\nTesting optimized session...")
        settings = ExploitSettings('v1')
        session = OptimizedSession(settings)
        
        optimized_times = []
        
        for url in test_urls:
            start = time.time()
            try:
                response = session.get(url)
            except:
                pass
            elapsed = time.time() - start
            optimized_times.append(elapsed)
            print(f"  {url}: {elapsed:.2f}s")
        
        print(f"\nResults:")
        print(f"Standard avg:  {statistics.mean(standard_times):.2f}s")
        print(f"Optimized avg: {statistics.mean(optimized_times):.2f}s")
        
        if statistics.mean(optimized_times) > 0:
            speedup = statistics.mean(standard_times) / statistics.mean(optimized_times)
            print(f"Session speedup: {speedup:.1f}x")


def benchmark_service_detection():
    """Benchmark service detection specifically."""
    print("\n=== Service Detection Benchmark ===")
    
    target_ports = [22, 23, 21, 80, 443]
    test_host = "127.0.0.1"  # Test against localhost
    
    if OPTIMIZATIONS_AVAILABLE:
        settings_v1 = ExploitSettings('v1')  # Aggressive
        settings_v2 = ExploitSettings('v2')  # Conservative
        
        print(f"Testing against {test_host} with ports {target_ports}")
        
        # Test V1 settings
        start = time.time()
        result_v1 = fast_service_check(test_host, target_ports, settings_v1)
        time_v1 = time.time() - start
        
        # Test V2 settings  
        start = time.time()
        result_v2 = fast_service_check(test_host, target_ports, settings_v2)
        time_v2 = time.time() - start
        
        print(f"V1 settings (aggressive): {time_v1:.2f}s, found port: {result_v1}")
        print(f"V2 settings (conservative): {time_v2:.2f}s, found port: {result_v2}")
        
        if time_v2 > 0:
            speedup = time_v2 / time_v1
            print(f"V1 vs V2 speedup: {speedup:.1f}x")


def run_all_benchmarks():
    """Run all performance benchmarks."""
    print("OpenWRTInvasion Performance Benchmark")
    print("=" * 40)
    
    if not OPTIMIZATIONS_AVAILABLE:
        print("⚠️  Performance optimizations not available")
        print("   Make sure exploit_performance.py is in the same directory")
        return
    
    try:
        benchmark_socket_checks()
        benchmark_http_sessions() 
        benchmark_service_detection()
        
        print("\n" + "=" * 40)
        print("✅ Benchmark completed!")
        print("\nTo use optimizations in exploits:")
        print("  python remote_command_execution_vulnerability_optimized.py --help")
        
    except KeyboardInterrupt:
        print("\n\n⏹️  Benchmark interrupted by user")
    except Exception as e:
        print(f"\n❌ Benchmark failed: {e}")


if __name__ == "__main__":
    run_all_benchmarks()