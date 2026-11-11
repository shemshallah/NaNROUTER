// Read-only logits transport from the *real* frozen HW0 unified decoder.
// This is NOT a trainable host model, and it is NOT the separate 43M hybrid.
// The NaN16 guest later computes full cross-entropy and candidate admission.
// Output: header + raw float32 bit patterns of log probabilities; 255 is -inf.
#include "nanlm/universe.hpp"
#include "nanlm/unified_wave.hpp"
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

static uint32_t bits(float x) {
  uint32_t u = 0;
  std::memcpy(&u, &x, sizeof(u));
  return u;
}
int main(int argc, char** argv) {
  try {
    if (argc != 6)
      throw std::invalid_argument("usage: trace ROOT TEXT PREV2 PREV1 MAX_ROWS");
    const unsigned h = static_cast<unsigned>(std::stoul(argv[3]));
    const unsigned a = static_cast<unsigned>(std::stoul(argv[4]));
    const unsigned cap = static_cast<unsigned>(std::stoul(argv[5]));
    if (h >= 255u || a >= 255u || cap == 0u || cap > 32u)
      throw std::invalid_argument("invalid context or trace bound");
    nanlm::Universe universe(argv[1]);
    nanlm::UnifiedWaveLanguage model(universe);
    std::ifstream source(argv[2], std::ios::binary);
    if (!source) throw std::runtime_error("decoder text unavailable");
    nanlm::UnifiedWaveLanguage::State state{};
    struct Row {uint8_t label; std::vector<uint32_t> logits;};
    std::vector<Row> rows;
    char ch = 0;
    while (source.get(ch)) {
      const auto label = static_cast<uint8_t>(static_cast<unsigned char>(ch));
      if (label == 255u) {state.reset(); continue;}
      if (state.length >= 2u &&
          state.history[state.length-2u] == h &&
          state.history[state.length-1u] == a &&
          rows.size() < cap) {
        const auto distribution = model.predict(state);
        Row row{};
        row.label = label;
        row.logits.reserve(256);
        for (size_t c = 0; c < nanlm::UnifiedWaveLanguage::N; ++c) {
          const double p = distribution.p[c];
          if (!std::isfinite(p) || p < 0.0 || p > 1.0)
            throw std::runtime_error("decoder yielded invalid probability");
          // Log-probabilities are equivalent logits up to additive constant.
          // This is a READOUT encoding, never a host optimizer/loss decision.
          const float logit = static_cast<float>(std::log(std::max(p, 1e-30)));
          if (!std::isfinite(logit))
            throw std::runtime_error("nonfinite encoded decoder logit");
          row.logits.push_back(bits(logit));
        }
        row.logits.push_back(0xFF800000u); // void byte 255 is NEVER a class
        rows.push_back(row);
      }
      model.observe(state,label);
    }
    if (rows.empty())
      throw std::runtime_error("no matching causal contexts in decoder text");
    std::cout<<"FROZEN_DECODER_TRACE_V1 "<<h<<" "<<a<<" "<<rows.size()<<"\n";
    std::cout<<std::uppercase<<std::hex<<std::setfill('0');
    for (const auto& row:rows) {
      std::cout<<std::dec<<static_cast<unsigned>(row.label)<<std::hex;
      for (uint32_t w:row.logits)
        std::cout<<" "<<std::setw(8)<<w;
      std::cout<<"\n";
    }
    return 0;
  } catch (const std::exception& e) {
    std::cerr<<"FROZEN_DECODER_TRACE_REJECT "<<e.what()<<"\n";
    return 1;
  }
}
