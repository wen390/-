CXX ?= c++
CXXFLAGS ?= -std=c++17 -O2 -Wall -Wextra -pedantic

.PHONY: all clean run-all

all: pcb_tail_router

pcb_tail_router: src/main.cpp include/pcb_tail_router.hpp
	$(CXX) $(CXXFLAGS) -Iinclude src/main.cpp -o pcb_tail_router

run-all: pcb_tail_router
	./pcb_tail_router --case data/case_01.csv --out results/case_01
	./pcb_tail_router --case data/case_02.csv --out results/case_02
	./pcb_tail_router --case data/case_03.csv --out results/case_03
	./pcb_tail_router --case data/case_04.csv --out results/case_04
	./pcb_tail_router --case data/case_05.csv --out results/case_05

clean:
	rm -f pcb_tail_router

