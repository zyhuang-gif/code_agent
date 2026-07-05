#include <fstream>
#include <string>

int main() {
    std::ifstream input("data/value.txt");
    std::string value;
    input >> value;
    return value == "ok" ? 0 : 1;
}
