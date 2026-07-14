#include <cstddef>
#include <cstdint>
#include <cstring>
#include <utility>
#include <vector>

#include <opencv2/core.hpp>
#include <opencv2/core/utils/logger.hpp>

#include "detection/tiled.hpp"
#include "geometry/geometry.hpp"
#include "light_ocr/types.hpp"
#include "model/bundle_data.hpp"

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data, std::size_t size) {
  cv::utils::logging::setLogLevel(cv::utils::logging::LOG_LEVEL_SILENT);
  if (size < sizeof(float) * 8) return 0;
  light_ocr::Quad quad;
  for (std::size_t index = 0; index < 4; ++index) {
    std::memcpy(&quad.points[index].x, data + index * sizeof(float) * 2, sizeof(float));
    std::memcpy(&quad.points[index].y, data + index * sizeof(float) * 2 + sizeof(float),
                sizeof(float));
  }
  cv::Mat image(64, 64, CV_8UC3, cv::Scalar(1, 2, 3));
  light_ocr::internal::GeometryConfig config{10, 1.5f};
  light_ocr::ResourceLimits limits;
  limits.max_temporary_bytes = size > 32 ? data[32] * 1024ull + 1 : 4096;
  (void)light_ocr::internal::sort_reading_order({quad}, config);
  (void)light_ocr::internal::crop_text_regions(image, {quad}, config, limits);
  (void)light_ocr::internal::plan_detection_axis(
      static_cast<std::uint32_t>(size), 1280, 128);
  if (size >= sizeof(float) * 18) {
    light_ocr::Quad second_quad;
    for (std::size_t index = 0; index < 4; ++index) {
      std::memcpy(&second_quad.points[index].x,
                  data + sizeof(float) * (8 + index * 2), sizeof(float));
      std::memcpy(&second_quad.points[index].y,
                  data + sizeof(float) * (9 + index * 2), sizeof(float));
    }
    double first_score = 0;
    double second_score = 0;
    std::memcpy(&first_score, data + sizeof(float) * 16, sizeof(float));
    std::memcpy(&second_score, data + sizeof(float) * 17, sizeof(float));
    std::vector<light_ocr::internal::TiledCandidate> candidates{
        {quad, first_score, 0, 0, {0, 0, 0, 1280, 1280},
         static_cast<std::uint8_t>(data[0] & 0x0f),
         static_cast<double>(data[1])},
        {second_quad, second_score, 1, 0, {1, 768, 0, 1280, 1280},
         static_cast<std::uint8_t>(data[2] & 0x0f),
         static_cast<double>(data[3])}};
    const light_ocr::internal::TiledDetectionConfig tiled{
        "tiled-v1", 1280, 128, 32, 32, 0.5, 0.8};
    (void)light_ocr::internal::merge_tiled_candidates(
        std::move(candidates), tiled);
  }
  return 0;
}
