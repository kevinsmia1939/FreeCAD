// SPDX-License-Identifier: LGPL-2.1-or-later
#pragma once
#if defined(_WIN32)
# if defined(ImplicitNativeWork_EXPORTS)
#  define ImplicitNativeWorkExport __declspec(dllexport)
# else
#  define ImplicitNativeWorkExport __declspec(dllimport)
# endif
#else
# define ImplicitNativeWorkExport __attribute__((visibility("default")))
#endif
