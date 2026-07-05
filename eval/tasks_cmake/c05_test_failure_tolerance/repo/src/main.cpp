#include "mathx/scale.hpp"

#include <cmath>
#include <stdexcept>

int main() {
    const double result = mathx::scale(3.0, 2.0);
    if (std::fabs(result - 6.0) > 1e-9) {
        throw std::runtime_error("bad scale");
    }
    return 0;
}
