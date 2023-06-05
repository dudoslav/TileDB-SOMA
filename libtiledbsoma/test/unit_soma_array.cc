/**
 * @file   unit_soma_array.cc
 *
 * @section LICENSE
 *
 * The MIT License
 *
 * @copyright Copyright (c) 2022 TileDB, Inc.
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 *
 * @section DESCRIPTION
 *
 * This file manages unit tests for the SOMAArray class
 */

#include <catch2/catch_template_test_macros.hpp>
#include <catch2/catch_test_macros.hpp>
#include <catch2/generators/catch_generators_all.hpp>
#include <catch2/matchers/catch_matchers_exception.hpp>
#include <catch2/matchers/catch_matchers_floating_point.hpp>
#include <catch2/matchers/catch_matchers_predicate.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>
#include <catch2/matchers/catch_matchers_templated.hpp>
#include <catch2/matchers/catch_matchers_vector.hpp>
#include <numeric>
#include <random>

#include <tiledb/tiledb>
#include <tiledbsoma/tiledbsoma>
#include "utils/util.h"

using namespace tiledb;
using namespace tiledbsoma;
using namespace Catch::Matchers;

#ifndef TILEDBSOMA_SOURCE_ROOT
#define TILEDBSOMA_SOURCE_ROOT "not_defined"
#endif

const std::string src_path = TILEDBSOMA_SOURCE_ROOT;

namespace {

std::tuple<std::string, uint64_t> create_array(
    const std::string& uri_in,
    Context& ctx,
    int num_cells_per_fragment = 10,
    int num_fragments = 1,
    bool overlap = false,
    bool allow_duplicates = false) {
    std::string uri = fmt::format(
        "{}-{}-{}-{}-{}",
        uri_in,
        num_cells_per_fragment,
        num_fragments,
        overlap,
        allow_duplicates);
    // Create array, if not reusing the existing array
    auto vfs = VFS(ctx);
    if (vfs.is_dir(uri)) {
        vfs.remove_dir(uri);
    }

    // Create schema
    ArraySchema schema(ctx, TILEDB_SPARSE);

    auto dim = Dimension::create<int64_t>(
        ctx, "d0", {0, std::numeric_limits<int64_t>::max() - 1});

    Domain domain(ctx);
    domain.add_dimension(dim);
    schema.set_domain(domain);

    auto attr = Attribute::create<int>(ctx, "a0");
    schema.add_attribute(attr);
    schema.set_allows_dups(allow_duplicates);
    schema.check();

    // Create array
    Array::create(uri, schema);

    uint64_t nnz = num_fragments * num_cells_per_fragment;

    if (allow_duplicates) {
        return {uri, nnz};
    }

    // Adjust nnz when overlap is enabled
    if (overlap) {
        nnz = (num_fragments + 1) / 2 * num_cells_per_fragment;
    }

    return {uri, nnz};
}

std::tuple<std::vector<int64_t>, std::vector<int>> write_array(
    const std::string& uri,
    std::shared_ptr<Context> ctx,
    int num_cells_per_fragment = 10,
    int num_fragments = 1,
    bool overlap = false,
    uint64_t timestamp = 1) {
    // Generate fragments in random order
    std::vector<int> frags(num_fragments);
    std::iota(frags.begin(), frags.end(), 0);
    std::shuffle(frags.begin(), frags.end(), std::random_device{});

    for (auto i = 0; i < num_fragments; ++i) {
        auto frag_num = frags[i];

        // Open array for writing
        Array array(*ctx, uri, TILEDB_WRITE, timestamp + i);
        if (LOG_DEBUG_ENABLED()) {
            array.schema().dump();
        }

        std::vector<int64_t> d0(num_cells_per_fragment);
        for (int j = 0; j < num_cells_per_fragment; j++) {
            // Overlap odd fragments when generating overlaps
            if (overlap && frag_num % 2 == 1) {
                d0[j] = j + num_cells_per_fragment * (frag_num - 1);
            } else {
                d0[j] = j + num_cells_per_fragment * frag_num;
            }
        }
        std::vector<int> a0(num_cells_per_fragment, frag_num);

        // Write data to array
        Query query(*ctx, array);
        query.set_layout(TILEDB_UNORDERED)
            .set_data_buffer("d0", d0)
            .set_data_buffer("a0", a0);
        query.submit();
        array.close();
    }

    Array rarray(*ctx, uri, TILEDB_READ, timestamp + num_fragments - 1);
    rarray.reopen();

    std::vector<int64_t> expected_d0(num_cells_per_fragment * num_fragments);
    std::vector<int> expected_a0(num_cells_per_fragment * num_fragments);

    Query query(*ctx, rarray);
    query.set_layout(TILEDB_UNORDERED)
        .set_data_buffer("d0", expected_d0)
        .set_data_buffer("a0", expected_a0);
    query.submit();

    rarray.close();

    expected_d0.resize(query.result_buffer_elements()["d0"].second);
    expected_a0.resize(query.result_buffer_elements()["a0"].second);

    return {expected_d0, expected_a0};
}

};  // namespace

TEST_CASE("SOMAArray: nnz") {
    auto num_fragments = GENERATE(1, 10);
    auto overlap = GENERATE(false, true);
    auto allow_duplicates = GENERATE(false, true);
    int num_cells_per_fragment = 128;
    auto timestamp = 10;

    SECTION(fmt::format(
        " - fragments={}, overlap={}, allow_duplicates={}",
        num_fragments,
        overlap,
        allow_duplicates)) {
        auto ctx = std::make_shared<Context>();

        // Create array at timestamp 10
        std::string base_uri = "mem://unit-test-array";
        auto [uri, expected_nnz] = create_array(
            base_uri,
            *ctx,
            num_cells_per_fragment,
            num_fragments,
            overlap,
            allow_duplicates);

        auto [expected_d0, expected_a0] = write_array(
            uri,
            ctx,
            num_cells_per_fragment,
            num_fragments,
            overlap,
            timestamp);

        // Get total cell num
        auto soma_array = SOMAArray::open(
            TILEDB_READ,
            ctx,
            uri,
            "",
            {},
            "auto",
            "auto",
            std::pair<uint64_t, uint64_t>(
                timestamp, timestamp + num_fragments - 1));

        uint64_t nnz = soma_array->nnz();
        REQUIRE(nnz == expected_nnz);

        std::vector<int64_t> shape = soma_array->shape();
        REQUIRE(shape.size() == 1);
        REQUIRE(shape[0] == std::numeric_limits<int64_t>::max());

        soma_array->submit();
        while (auto batch = soma_array->read_next()) {
            auto arrbuf = batch.value();
            REQUIRE(arrbuf->names() == std::vector<std::string>({"d0", "a0"}));
            REQUIRE(arrbuf->num_rows() == nnz);

            auto d0span = arrbuf->at("d0")->data<int64_t>();
            auto a0span = arrbuf->at("a0")->data<int>();

            std::vector<int64_t> d0col(d0span.begin(), d0span.end());
            std::vector<int> a0col(a0span.begin(), a0span.end());

            REQUIRE(d0col == expected_d0);
            REQUIRE(a0col == expected_a0);
        }
        soma_array->close();
    }
}

TEST_CASE("SOMAArray: nnz with timestamp") {
    auto num_fragments = GENERATE(1, 10);
    auto overlap = GENERATE(false, true);
    auto allow_duplicates = GENERATE(false, true);
    int num_cells_per_fragment = 128;

    SECTION(fmt::format(
        " - fragments={}, overlap={}, allow_duplicates={}",
        num_fragments,
        overlap,
        allow_duplicates)) {
        auto ctx = std::make_shared<Context>();

        // Create array at timestamp 10
        std::string base_uri = "mem://unit-test-array";
        const auto& [uri, expected_nnz] = create_array(
            base_uri,
            *ctx,
            num_cells_per_fragment,
            num_fragments,
            overlap,
            allow_duplicates);
        write_array(
            uri, ctx, num_cells_per_fragment, num_fragments, overlap, 10);

        // Write more data to the array at timestamp 40, which will be
        // not be included in the nnz call with a timestamp
        write_array(
            uri, ctx, num_cells_per_fragment, num_fragments, overlap, 40);

        // Get total cell num at timestamp (0, 20)
        std::pair<uint64_t, uint64_t> timestamp{0, 20};
        auto soma_array = SOMAArray::open(
            TILEDB_READ, ctx, uri, "nnz", {}, "auto", "auto", timestamp);

        uint64_t nnz = soma_array->nnz();
        REQUIRE(nnz == expected_nnz);
    }
}

TEST_CASE("SOMAArray: nnz with consolidation") {
    auto num_fragments = GENERATE(1, 10);
    auto overlap = GENERATE(false, true);
    auto allow_duplicates = GENERATE(false, true);
    auto vacuum = GENERATE(false, true);
    int num_cells_per_fragment = 128;

    SECTION(fmt::format(
        " - fragments={}, overlap={}, allow_duplicates={}, vacuum={}",
        num_fragments,
        overlap,
        allow_duplicates,
        vacuum)) {
        auto ctx = std::make_shared<Context>();

        // Create array at timestamp 10
        std::string base_uri = "mem://unit-test-array";
        const auto& [uri, expected_nnz] = create_array(
            base_uri,
            *ctx,
            num_cells_per_fragment,
            num_fragments,
            overlap,
            allow_duplicates);
        write_array(
            uri, ctx, num_cells_per_fragment, num_fragments, overlap, 10);

        // Write more data to the array at timestamp 20, which will be
        // duplicates of the data written at timestamp 10
        // The duplicates get merged into one fragment during consolidation.
        write_array(
            uri, ctx, num_cells_per_fragment, num_fragments, overlap, 20);

        // Consolidate and optionally vacuum
        Array::consolidate(*ctx, uri);
        if (vacuum) {
            Array::vacuum(*ctx, uri);
        }

        // Get total cell num
        auto soma_array = SOMAArray::open(
            TILEDB_READ, ctx, uri, "nnz", {}, "auto", "auto");

        uint64_t nnz = soma_array->nnz();
        if (allow_duplicates) {
            // Since we wrote twice
            REQUIRE(nnz == 2 * expected_nnz);
        } else {
            REQUIRE(nnz == expected_nnz);
        }
    }
}

TEST_CASE("SOMAArray: metadata") {
    auto ctx = std::make_shared<Context>();

    std::string base_uri = "mem://unit-test-array";
    const auto& [uri, expected_nnz] = create_array(base_uri, *ctx);

    auto soma_array = SOMAArray::open(
        TILEDB_WRITE,
        ctx,
        uri,
        "metadata_test",
        {},
        "auto",
        "auto",
        std::pair<uint64_t, uint64_t>(1, 1));
    int32_t val = 100;
    soma_array->set_metadata("md", TILEDB_INT32, 1, &val);
    soma_array->close();

    soma_array->open(TILEDB_READ, std::pair<uint64_t, uint64_t>(1, 1));
    REQUIRE(soma_array->has_metadata("md") == true);
    REQUIRE(soma_array->metadata_num() == 1);

    auto mdval = soma_array->get_metadata(0);
    REQUIRE(std::get<MetadataInfo::key>(mdval) == "md");
    REQUIRE(std::get<MetadataInfo::dtype>(mdval) == TILEDB_INT32);
    REQUIRE(std::get<MetadataInfo::num>(mdval) == 1);
    REQUIRE(*((const int32_t*)std::get<MetadataInfo::value>(mdval)) == 100);

    mdval = soma_array->get_metadata("md");
    REQUIRE(std::get<MetadataInfo::key>(mdval) == "md");
    REQUIRE(std::get<MetadataInfo::dtype>(mdval) == TILEDB_INT32);
    REQUIRE(std::get<MetadataInfo::num>(mdval) == 1);
    REQUIRE(*((const int32_t*)std::get<MetadataInfo::value>(mdval)) == 100);
    soma_array->close();

    soma_array->open(TILEDB_WRITE, std::pair<uint64_t, uint64_t>(2, 2));
    soma_array->delete_metadata("md");
    soma_array->close();

    soma_array->open(TILEDB_READ, std::pair<uint64_t, uint64_t>(3, 3));
    REQUIRE(soma_array->has_metadata("md") == false);
    REQUIRE(soma_array->metadata_num() == 0);
    soma_array->close();
}