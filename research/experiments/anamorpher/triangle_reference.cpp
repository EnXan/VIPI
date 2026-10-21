// Independent scalar port of the image-rs 0.25.9 Triangle formula.
// Reference: https://github.com/image-rs/image/blob/v0.25.9/src/imageops/sample.rs
// Operates on opaque RGB8; reads/writes raw bytes. This is not the Rust crate.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>

struct Taps { int first; std::vector<float> weights; };

std::vector<Taps> axis(int source, int target) {
    const float ratio = float(source) / float(target);
    const float scale = std::max(1.0f, ratio);
    std::vector<Taps> result;
    for (int output = 0; output < target; ++output) {
        float center = (float(output) + 0.5f) * ratio;
        int first = std::clamp(int(std::floor(center-scale)), 0, source-1);
        int end = std::clamp(int(std::ceil(center+scale)), first+1, source);
        center -= 0.5f;
        Taps taps{first, {}};
        float sum = 0;
        for (int input = first; input < end; ++input) {
            const float distance = std::abs((float(input)-center)/scale);
            const float weight = distance < 1.0f ? 1.0f-distance : 0.0f;
            taps.weights.push_back(weight);
            sum += weight;
        }
        for (float &weight : taps.weights) weight /= sum;
        result.push_back(taps);
    }
    return result;
}

int main(int argc, char **argv) {
    try {
        if (argc != 7) throw std::runtime_error("Use INPUT.raw OUTPUT.raw width height new_width new_height");
        const int width=std::stoi(argv[3]), height=std::stoi(argv[4]);
        const int new_width=std::stoi(argv[5]), new_height=std::stoi(argv[6]);
        if (std::min({width,height,new_width,new_height}) < 1)
            throw std::runtime_error("Dimensions must be positive");
        const auto x_taps=axis(width,new_width), y_taps=axis(height,new_height);
        std::vector<uint8_t> input(size_t(width)*height*3);
        std::ifstream file(argv[1], std::ios::binary);
        if (!file.read(reinterpret_cast<char*>(input.data()), input.size()))
            throw std::runtime_error("Invalid input raster length");
        std::vector<float> intermediate(size_t(width)*new_height*3, 0);
        for (int y=0; y<new_height; ++y) {
            const auto &taps=y_taps[y];
            for (int x=0; x<width; ++x) for (int c=0; c<3; ++c) {
                float sum=0;
                for (size_t i=0; i<taps.weights.size(); ++i)
                    sum += float(input[(size_t(taps.first+i)*width+x)*3+c])*taps.weights[i];
                intermediate[(size_t(y)*width+x)*3+c]=sum;
            }
        }
        std::vector<uint8_t> output(size_t(new_width)*new_height*3);
        for (int x=0; x<new_width; ++x) {
            const auto &taps=x_taps[x];
            for (int y=0; y<new_height; ++y) for (int c=0; c<3; ++c) {
                float sum=0;
                for (size_t i=0; i<taps.weights.size(); ++i)
                    sum += intermediate[(size_t(y)*width+taps.first+i)*3+c]*taps.weights[i];
                output[(size_t(y)*new_width+x)*3+c]=uint8_t(std::round(std::clamp(sum,0.0f,255.0f)));
            }
        }
        std::ofstream destination(argv[2], std::ios::binary);
        if (!destination.write(reinterpret_cast<const char*>(output.data()), output.size()))
            throw std::runtime_error("Failed to write output");
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
