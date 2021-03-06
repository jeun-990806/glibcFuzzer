import os
import re
import importlib
import subprocess
import time

import cffi

import fileManagement
import dataType
import cDataMaker


class Fuzzer:
    __ffi = cffi.FFI()
    __mutators = []
    __cDataMaker = cDataMaker.CDataMaker()
    __arguments = []
    __ptraceSyscalls = set()
    __foundedSyscallSet = set()
    __inputSyscallsTable = []
    __pid = str(os.getpid())

    __executionNum = 0

    def __init__(self, path):
        self.__targetCodePath = path
        self.__targetFileName = path[path.rfind('/') + 1:path.rfind('.')]
        self.__properties = ''.join(open('properties/' + self.__targetFileName + '.pro', 'r').readlines())
        self.__getArguments()
        self.__setMutators()
        self.__targetFunction = importlib.import_module('target').lib

    def __del__(self):
        print('total number of executions: %d' % self.__executionNum)

    def __getArguments(self):
        argumentRE = '^ARG[1-9][0-9]*=([^;]*);'
        for arg in re.findall(argumentRE, self.__properties, re.MULTILINE):
            self.__arguments.append(dataType.DataType(arg))

    def __setMutators(self):
        self.__mutators = [arg.getMutator() for arg in self.__arguments]

    def __makeMutationSequence(self):
        return [mutator.getMutation() for mutator in self.__mutators]

    def __exportInputs(self, mutations):
        fileManagement.saveData(mutations, 'result/' + self.__targetFileName + '/input/' +
                                self.__targetFileName + '_input_' + str(self.__executionNum) + '.list')

    def __exportOutputs(self):
        with open('result/' + self.__targetFileName + '/output/' + self.__targetFileName
                  + '_output_' + str(self.__executionNum) + '.txt', 'w') as f:
            log = ''.join(self.__getTraceLog())
            f.write(log)

    def executeWithMutationSequence(self):
        self.__executionNum += 1
        newInput = self.__makeMutationSequence()
        ptrace = subprocess.Popen(['./ptrace', self.__pid], stdout=subprocess.PIPE, encoding='utf-8')
        subprocess.call('echo %s > /sys/kernel/debug/tracing/set_ftrace_notrace_pid' % str(ptrace.pid), shell=True)
        try:
            self.__targetFunction.target(*[self.__cDataMaker.castToCDataType(i, t.makeFormalDataType())
                                           for i, t in zip(newInput, self.__arguments)])
            time.sleep(.001)
            ptrace.send_signal(10)
            foundedSyscalls = set(ptrace.stdout.read().split('\n')[:-1])
            ptrace.wait()
        finally:
            ptrace.terminate()

        if len(foundedSyscalls - self.__ptraceSyscalls) != 0:
            print('found new system call')
            self.__ptraceSyscalls = self.__ptraceSyscalls | foundedSyscalls
            self.__exportInputs(newInput)
            self.__exportOutputs()

    def __checkNewSyscall(self, newSyscalls):
        if len(newSyscalls - self.__foundedSyscallSet) != 0:
            self.__updateFoundedSyscalls(newSyscalls)
            return True
        return False

    def __getTraceLog(self):
        traceFile = open('/sys/kernel/debug/tracing/trace', 'r')
        traceLog = traceFile.readlines()
        traceFile.close()
        return traceLog

    def __getSyscallSet(self):
        traceLog = self.__getTraceLog()
        syscallSet = set()
        readOn = False
        for line in traceLog:
            if 'start_ftrace' in line:
                readOn = True
                continue
            if 'stop_ftrace' in line:
                break
            if readOn and 'sys_enter:' in line and self.__pid in line:
                syscallSet.add(line[line.find('NR ') + 3:line.rfind(' (')])
        return syscallSet

    def __updateFoundedSyscalls(self, newSyscalls):
        self.__foundedSyscallSet = self.__foundedSyscallSet | newSyscalls
