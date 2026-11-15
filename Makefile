CXX      ?= g++
CXXFLAGS ?= -O2 -std=c++17 -Wall -Wextra

build/scorer: scorer.cpp
	mkdir -p build
	$(CXX) $(CXXFLAGS) -o $@ $<

clean:
	rm -rf build

.PHONY: clean
