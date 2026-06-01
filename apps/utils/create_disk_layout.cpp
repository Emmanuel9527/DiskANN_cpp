// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT license.

#include <cmath>
#include <cstring>
#include <fstream>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

#include "utils.h"
#include "disk_utils.h"
#include "cached_io.h"

template <typename T> int create_disk_layout(char **argv, bool use_block_shuffling, uint32_t max_iterations,
                                             double gain_threshold)
{
    std::string base_file(argv[2]);
    std::string vamana_file(argv[3]);
    std::string output_file(argv[4]);
    if (use_block_shuffling)
        diskann::create_disk_layout_block_shuffling<T>(base_file, vamana_file, output_file, std::string(""),
                                                       max_iterations, gain_threshold);
    else
        diskann::create_disk_layout<T>(base_file, vamana_file, output_file);
    return 0;
}

int main(int argc, char **argv)
{
    if (argc != 5 && argc != 6 && argc != 7 && argc != 8)
    {
        std::cout << argv[0]
                  << " data_type <float/int8/uint8> data_bin "
                     "vamana_index_file output_diskann_index_file "
                     "[layout_mode <default/block_shuffle>] [max_iterations] [gain_threshold]"
                  << std::endl;
        exit(-1);
    }

    bool use_block_shuffling = false;
    uint32_t max_iterations = 3;
    double gain_threshold = 0.0;
    if (argc >= 6)
    {
        const std::string layout_mode(argv[5]);
        if (layout_mode == "block_shuffle")
            use_block_shuffling = true;
        else if (layout_mode != "default")
        {
            std::cout << "unsupported layout_mode. use default/block_shuffle " << std::endl;
            return -3;
        }
    }
    if (argc >= 7)
        max_iterations = (uint32_t)std::stoul(argv[6]);
    if (argc >= 8)
        gain_threshold = std::stod(argv[7]);

    int ret_val = -1;
    if (std::string(argv[1]) == std::string("float"))
        ret_val = create_disk_layout<float>(argv, use_block_shuffling, max_iterations, gain_threshold);
    else if (std::string(argv[1]) == std::string("int8"))
        ret_val = create_disk_layout<int8_t>(argv, use_block_shuffling, max_iterations, gain_threshold);
    else if (std::string(argv[1]) == std::string("uint8"))
        ret_val = create_disk_layout<uint8_t>(argv, use_block_shuffling, max_iterations, gain_threshold);
    else
    {
        std::cout << "unsupported type. use int8/uint8/float " << std::endl;
        ret_val = -2;
    }
    return ret_val;
}
