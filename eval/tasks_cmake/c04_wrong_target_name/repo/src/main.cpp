#include "mathx/add.hpp"

#include <stdexcept>

int main() {
    if (mathx::add(10, 5) != 15) {
        throw std::runtime_error("bad add");
    }
    return 0;
}
