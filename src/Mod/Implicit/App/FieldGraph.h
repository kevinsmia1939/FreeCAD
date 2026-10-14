// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <cstddef>
#include <string>

#include <Mod/Implicit/ImplicitGlobal.h>

#include "Field.h"

namespace Implicit
{

class ImplicitExport FieldGraph
{
public:
    static constexpr int CurrentSchema = 1;
    static constexpr std::size_t MaximumBytes = 4 * 1024 * 1024;
    static constexpr std::size_t MaximumDepth = 128;
    static constexpr std::size_t MaximumNodes = 4096;

    static FieldPtr parse(const std::string& serialized);
    static std::string canonicalize(const std::string& serialized);
};

}  // namespace Implicit
