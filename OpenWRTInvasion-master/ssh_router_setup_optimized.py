#!/usr/bin/env python3
"""
Optimized SSH Router Setup Script
High-performance version with parallel execution, connection pooling, and advanced error handling
"""

import paramiko
import time
import sys
import threading
import concurrent.futures
from typing import List, Dict, Tuple, Optional
import logging
from dataclasses import dataclass
from contextlib import contextmanager
import json
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('ssh_router_setup.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class SSHConfig:
    """SSH connection configuration"""
    hostname: str
    username: str
    password: str
    port: int = 22
    timeout: int = 30
    max_retries: int = 3
    retry_delay: float = 2.0

@dataclass
class CommandResult:
    """Result of command execution"""
    command: str
    success: bool
    output: str
    error: str
    execution_time: float
    retry_count: int = 0

class OptimizedSSHClient:
    """High-performance SSH client with connection pooling and parallel execution"""
    
    def __init__(self, config: SSHConfig):
        self.config = config
        self.ssh_client: Optional[paramiko.SSHClient] = None
        self.sftp_client: Optional[paramiko.SFTPClient] = None
        self._lock = threading.Lock()
        self._connected = False
        
    def __enter__(self):
        self.connect()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        
    def connect(self) -> bool:
        """Establish SSH connection with retry logic"""
        for attempt in range(self.config.max_retries):
            try:
                with self._lock:
                    if self._connected and self.ssh_client:
                        return True
                        
                    self.ssh_client = paramiko.SSHClient()
                    self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    
                    logger.info(f"Connecting to {self.config.hostname} (attempt {attempt + 1}/{self.config.max_retries})")
                    
                    self.ssh_client.connect(
                        hostname=self.config.hostname,
                        username=self.config.username,
                        password=self.config.password,
                        port=self.config.port,
                        timeout=self.config.timeout,
                        look_for_keys=False,
                        allow_agent=False
                    )
                    
                    self._connected = True
                    logger.info("Successfully connected to router!")
                    return True
                    
            except paramiko.AuthenticationException:
                logger.error("Authentication failed. Please check credentials.")
                if attempt == self.config.max_retries - 1:
                    raise
            except paramiko.SSHException as e:
                logger.warning(f"SSH error (attempt {attempt + 1}): {e}")
                if attempt == self.config.max_retries - 1:
                    raise
            except Exception as e:
                logger.warning(f"Connection error (attempt {attempt + 1}): {e}")
                if attempt == self.config.max_retries - 1:
                    raise
                    
            if attempt < self.config.max_retries - 1:
                time.sleep(self.config.retry_delay * (attempt + 1))
                
        return False
        
    def disconnect(self):
        """Close SSH connection"""
        with self._lock:
            if self.sftp_client:
                self.sftp_client.close()
                self.sftp_client = None
                
            if self.ssh_client:
                self.ssh_client.close()
                self.ssh_client = None
                
            self._connected = False
            logger.info("SSH connection closed.")
            
    def execute_command(self, command: str, timeout: int = 60) -> CommandResult:
        """Execute a single command with timeout and retry logic"""
        start_time = time.time()
        
        for retry in range(self.config.max_retries):
            try:
                if not self._connected:
                    self.connect()
                    
                logger.info(f"Executing: {command}")
                
                stdin, stdout, stderr = self.ssh_client.exec_command(
                    command, 
                    timeout=timeout
                )
                
                # Read output with timeout
                output = stdout.read().decode('utf-8', errors='ignore')
                error = stderr.read().decode('utf-8', errors='ignore')
                
                execution_time = time.time() - start_time
                
                # Check if command was successful (exit code 0)
                exit_code = stdout.channel.recv_exit_status()
                success = exit_code == 0
                
                result = CommandResult(
                    command=command,
                    success=success,
                    output=output,
                    error=error,
                    execution_time=execution_time,
                    retry_count=retry
                )
                
                if success:
                    logger.info(f"Command completed successfully in {execution_time:.2f}s")
                else:
                    logger.warning(f"Command failed with exit code {exit_code}")
                    
                return result
                
            except Exception as e:
                logger.warning(f"Command execution failed (retry {retry + 1}): {e}")
                if retry == self.config.max_retries - 1:
                    execution_time = time.time() - start_time
                    return CommandResult(
                        command=command,
                        success=False,
                        output="",
                        error=str(e),
                        execution_time=execution_time,
                        retry_count=retry + 1
                    )
                time.sleep(self.config.retry_delay)
                
    def execute_commands_parallel(self, commands: List[str], max_workers: int = 3) -> List[CommandResult]:
        """Execute multiple commands in parallel"""
        logger.info(f"Executing {len(commands)} commands in parallel (max {max_workers} workers)")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all commands
            future_to_command = {
                executor.submit(self.execute_command, cmd): cmd 
                for cmd in commands
            }
            
            results = []
            for future in concurrent.futures.as_completed(future_to_command):
                command = future_to_command[future]
                try:
                    result = future.result()
                    results.append(result)
                    logger.info(f"Completed: {command}")
                except Exception as e:
                    logger.error(f"Command {command} generated exception: {e}")
                    results.append(CommandResult(
                        command=command,
                        success=False,
                        output="",
                        error=str(e),
                        execution_time=0.0
                    ))
                    
        return results
        
    def execute_commands_sequential(self, commands: List[str]) -> List[CommandResult]:
        """Execute commands sequentially with smart delays"""
        results = []
        
        for i, command in enumerate(commands):
            logger.info(f"[{i+1}/{len(commands)}] Executing: {command}")
            
            result = self.execute_command(command)
            results.append(result)
            
            # Smart delay based on command type and result
            if not result.success:
                delay = self.config.retry_delay * 2  # Longer delay on failure
            elif "install" in command.lower() or "update" in command.lower():
                delay = 3.0  # Longer delay for package operations
            else:
                delay = 1.0  # Short delay for other commands
                
            if i < len(commands) - 1:  # Don't delay after last command
                time.sleep(delay)
                
        return results

class RouterSetupManager:
    """Manages router setup operations with performance optimization"""
    
    def __init__(self, config: SSHConfig):
        self.config = config
        self.results: List[CommandResult] = []
        
    def get_optimized_commands(self) -> List[str]:
        """Get optimized command sequence for router setup"""
        return [
            "opkg update",
            "opkg install luci-app-mwan3",
            "opkg install luci-app-mwan3 luci-i18n-mwan3-zh-cn",  # Install with Chinese language pack
            "/etc/init.d/mwan3 enable",
            "/etc/init.d/mwan3 start",
            "uci show mwan3",  # Verify installation
        ]
        
    def get_parallel_commands(self) -> List[str]:
        """Get commands that can be executed in parallel"""
        return [
            "opkg list-installed | grep mwan3",
            "uci show network",
            "uci show firewall",
        ]
        
    def setup_router(self, use_parallel: bool = True) -> bool:
        """Main setup function with performance optimization"""
        logger.info("Starting optimized router setup...")
        
        with OptimizedSSHClient(self.config) as ssh_client:
            # Execute main setup commands
            if use_parallel:
                # Try parallel execution for compatible commands
                parallel_commands = self.get_parallel_commands()
                parallel_results = ssh_client.execute_commands_parallel(parallel_commands)
                self.results.extend(parallel_results)
                
                # Execute sequential commands that have dependencies
                sequential_commands = self.get_optimized_commands()
                sequential_results = ssh_client.execute_commands_sequential(sequential_commands)
                self.results.extend(sequential_results)
            else:
                # Fallback to sequential execution
                all_commands = self.get_optimized_commands() + self.get_parallel_commands()
                sequential_results = ssh_client.execute_commands_sequential(all_commands)
                self.results.extend(sequential_results)
                
        return self.analyze_results()
        
    def analyze_results(self) -> bool:
        """Analyze command execution results"""
        total_commands = len(self.results)
        successful_commands = sum(1 for r in self.results if r.success)
        total_time = sum(r.execution_time for r in self.results)
        
        logger.info(f"\n{'='*60}")
        logger.info("EXECUTION SUMMARY")
        logger.info(f"{'='*60}")
        logger.info(f"Total commands: {total_commands}")
        logger.info(f"Successful: {successful_commands}")
        logger.info(f"Failed: {total_commands - successful_commands}")
        logger.info(f"Total execution time: {total_time:.2f}s")
        logger.info(f"Average time per command: {total_time/total_commands:.2f}s")
        
        # Show failed commands
        failed_commands = [r for r in self.results if not r.success]
        if failed_commands:
            logger.warning(f"\nFAILED COMMANDS:")
            for result in failed_commands:
                logger.warning(f"  - {result.command}")
                logger.warning(f"    Error: {result.error}")
                
        # Save detailed results
        self.save_results()
        
        return successful_commands == total_commands
        
    def save_results(self):
        """Save execution results to JSON file"""
        results_data = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "config": {
                "hostname": self.config.hostname,
                "username": self.config.username,
                "port": self.config.port
            },
            "summary": {
                "total_commands": len(self.results),
                "successful": sum(1 for r in self.results if r.success),
                "total_time": sum(r.execution_time for r in self.results)
            },
            "results": [
                {
                    "command": r.command,
                    "success": r.success,
                    "output": r.output,
                    "error": r.error,
                    "execution_time": r.execution_time,
                    "retry_count": r.retry_count
                }
                for r in self.results
            ]
        }
        
        with open("ssh_setup_results.json", "w") as f:
            json.dump(results_data, f, indent=2)
            
        logger.info("Detailed results saved to ssh_setup_results.json")

def main():
    """Main function with configuration and execution"""
    print("Optimized OpenWrt Router SSH Setup Script")
    print("=" * 50)
    
    # Configuration - you can modify these values
    config = SSHConfig(
        hostname="192.168.2.1",
        username="root",
        password="@appDEV1234!!!!",
        port=22,
        timeout=30,
        max_retries=3,
        retry_delay=2.0
    )
    
    # Create setup manager
    setup_manager = RouterSetupManager(config)
    
    try:
        # Execute setup with parallel processing
        success = setup_manager.setup_router(use_parallel=True)
        
        if success:
            print("\n✅ Router setup completed successfully!")
            sys.exit(0)
        else:
            print("\n❌ Router setup completed with errors. Check logs for details.")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n⚠️ Setup interrupted by user.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Setup failed with error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
