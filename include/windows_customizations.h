// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT license.

#pragma once

// Controls symbol visibility when DiskANN is built or consumed as a Windows DLL.
// Public C++ access controls who may call a member; this macro controls whether
// the linker exports/imports the symbol across DLL boundaries. It is empty on
// non-Windows platforms.
#ifdef _WINDOWS

#ifdef _WINDLL
#define DISKANN_DLLEXPORT __declspec(dllexport)
#else
#define DISKANN_DLLEXPORT __declspec(dllimport)
#endif

#else
#define DISKANN_DLLEXPORT
#endif
