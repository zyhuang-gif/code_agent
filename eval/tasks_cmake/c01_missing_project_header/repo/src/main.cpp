#include "mathx/add.hpp"

#include <stdexcept>

namespace mathx {
int add(int a, int b) {
    return a + b;
}
}

int main() {
    if (mathx::add(2, 3) != 5) {
        throw std::runtime_error("bad add");
    }
    return 0;
}
