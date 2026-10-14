// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <FCGlobal.h>

#ifndef ImplicitExport
# ifdef Implicit_EXPORTS
#  define ImplicitExport FREECAD_DECL_EXPORT
# else
#  define ImplicitExport FREECAD_DECL_IMPORT
# endif
#endif
