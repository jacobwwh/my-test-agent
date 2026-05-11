CXX ?= g++
CXXFLAGS ?= -std=c++17 -Wall -Wextra -O0 -g -Iinclude
TEST_FILE ?= tests/testagent/generated/test.cpp
TEST_BINARY ?= build/testagent/test_binary
REPORT_DIR ?= build/testagent
SOURCES := $(wildcard src/*.cpp)

.PHONY: testagent-test clean

testagent-test:
	mkdir -p $(dir $(TEST_BINARY)) $(REPORT_DIR)
	$(CXX) $(CXXFLAGS) $(SOURCES) $(TEST_FILE) -o $(TEST_BINARY)
	$(TEST_BINARY)

clean:
	rm -rf build tests/testagent/generated
