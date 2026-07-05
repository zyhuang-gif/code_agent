#include <boost/graph/adjacency_list.hpp>

int main() {
    boost::adjacency_list graph;
    return boost::num_vertices(graph) == 0 ? 0 : 1;
}
