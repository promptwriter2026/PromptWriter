# Third-Party Notices

PWLP (PromptWriter) is licensed under the MIT License (see [LICENSE](LICENSE)).
PWLP itself is independent of the projects below; they are used as unmodified
dependencies or are bundled inside dependency packages.

This file lists the third-party components required by or shipped with PWLP,
their licenses, and the notices that must be retained when redistributing the
app. The full license text for each package is included in that package's
distribution (`*.dist-info/licenses/` inside the virtual environment) and is
also available from the package's project page.

## Direct dependencies

| Component | Version tested | License | Copyright / attribution |
|---|---|---|---|
| CustomTkinter | 6.0.0 | MIT | Copyright (c) 2023 Tom Schimansky |
| tkinterdnd2 | 0.6.3 | MIT | Copyright (c) 2020 Philippe Gagné |
| TkDND (native files bundled inside tkinterdnd2) | 2.10.2 | TkDND permissive license (see below) | Copyright George Petasis, NCSR "Demokritos" |
| Requests | 2.34.2 | Apache-2.0 | Requests, Copyright 2019 Kenneth Reitz |
| Google Gen AI SDK (`google-genai`) | 2.28.0 | Apache-2.0 | Copyright Google LLC |
| Pillow | 12.3.0 | MIT-CMU | PIL: Copyright © 1997-2011 Secret Labs AB; © 1995-2011 Fredrik Lundh and contributors. Pillow: Copyright © 2010 Jeffrey A. Clark and contributors |
| nvidia-ml-py (`pynvml`) | 13.615.71 | BSD (3-clause) | Copyright (c) 2011-2025, NVIDIA Corporation |
| Roboto fonts (bundled inside CustomTkinter) | — | Apache-2.0 | Copyright 2011 Google Inc. |
| certifi (dependency of Requests) | 2026.7.22 | MPL-2.0 | Copyright Kenneth Reitz and certifi contributors |

The `groq` Python SDK is not used by PWLP; Groq is accessed through its
OpenAI-compatible REST API with `requests`, so the SDK is not a dependency.

## MIT License

Applies to CustomTkinter and tkinterdnd2.

```
Copyright (c) 2023 Tom Schimansky
Copyright (c) 2020 Philippe Gagné

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Apache License 2.0 components

Requests, `google-genai`, and the Roboto fonts bundled with CustomTkinter are
licensed under the Apache License, Version 2.0
(https://www.apache.org/licenses/LICENSE-2.0). When redistributing PWLP with
these components, keep their `LICENSE` files (and the Requests `NOTICE` below)
with the distribution, and retain any NOTICE files provided by the packages.

Requests `NOTICE`:

```
Requests
Copyright 2019 Kenneth Reitz
```

## TkDND notice

The TkDND files bundled inside the tkinterdnd2 wheel carry this notice, which
must be retained in distributions:

```
This software is copyrighted by:
George Petasis, National Centre for Scientific Research "Demokritos",
Aghia Paraskevi, Athens, Greece.
e-mail: petasis@iit.demokritos.gr

The following terms apply to all files associated
with the software unless explicitly disclaimed in individual files.

The authors hereby grant permission to use, copy, modify, distribute,
and license this software and its documentation for any purpose, provided
that existing copyright notices are retained in all copies and that this
notice is included verbatim in any distributions. No written agreement,
license, or royalty fee is required for any of the authorized uses.
Modifications to this software may be copyrighted by their authors
and need not follow the licensing terms described here, provided that
the new terms are clearly indicated on the first page of each file where
they apply.

IN NO EVENT SHALL THE AUTHORS OR DISTRIBUTORS BE LIABLE TO ANY PARTY
FOR DIRECT, INDIRECT, SPECIAL, INCIDENTAL, OR CONSEQUENTIAL DAMAGES
ARISING OUT OF THE USE OF THIS SOFTWARE, ITS DOCUMENTATION, OR ANY
DERIVATIVES THEREOF, EVEN IF THE AUTHORS HAVE BEEN ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.

THE AUTHORS AND DISTRIBUTORS SPECIFICALLY DISCLAIM ANY WARRANTIES,
INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE, AND NON-INFRINGEMENT. THIS SOFTWARE
IS PROVIDED ON AN "AS IS" BASIS, AND THE AUTHORS AND DISTRIBUTORS HAVE
NO OBLIGATION TO PROVIDE MAINTENANCE, SUPPORT, UPDATES, ENHANCEMENTS, OR
MODIFICATIONS.
```

## nvidia-ml-py license (BSD 3-Clause)

```
Copyright (c) 2011-2025, NVIDIA Corporation.  All rights reserved.

Redistribution and use in source and binary forms, with or without modification,
are permitted provided that the following conditions are met:

- Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

- Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

- Neither the name of the NVIDIA Corporation nor the names of its contributors
  may be used to endorse or promote products derived from this software
  without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## Pillow (MIT-CMU)

Pillow is distributed under the MIT-CMU license. Copyright notices as listed
in the table above; the complete terms are in Pillow's `LICENSE` file.

## Other transitive dependencies

PWLP's installed environment may also contain these packages (pulled in by the
dependencies above). All are permissively licensed:

| Package | License |
|---|---|
| annotated-types | MIT |
| anyio | MIT |
| cffi | MIT |
| charset-normalizer | MIT |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| darkdetect | BSD-3-Clause |
| distro | Apache-2.0 |
| google-auth | Apache-2.0 |
| h11 | MIT |
| httpcore | BSD-3-Clause |
| httpx | BSD-3-Clause |
| idna | BSD-3-Clause |
| packaging | Apache-2.0 OR BSD-2-Clause |
| pyasn1 | BSD-2-Clause |
| pyasn1_modules | BSD-2-Clause |
| pycparser | BSD-3-Clause |
| pydantic | MIT |
| pydantic-core | MIT |
| sniffio | MIT |
| tenacity | Apache-2.0 |
| typing_extensions | PSF-2.0 |
| typing-inspection | MIT |
| urllib3 | MIT |
| websockets | BSD-3-Clause |
| certifi | MPL-2.0 |

`certifi` is licensed under the Mozilla Public License 2.0; PWLP and its
distributions ship certifi unmodified, so its file-level copyleft terms are
satisfied by retaining its license and source availability.

## Runtime platform

- Python — PSF License 2.0.
- Tcl/Tk (used by tkinter) — BSD-style Tcl/Tk license.

## Trademarks

LM Studio, Gemini, Groq, NVIDIA, and other names are trademarks of their
respective owners. They are used here only to describe compatibility. PWLP is
not affiliated with, endorsed by, or sponsored by these companies.

## Bundled PWLP assets

`promptwriter/assets/promptwriter.ico` and
`promptwriter/assets/promptwriter_preview.png` are original artwork generated
by this project's `tools/generate_app_icon.py`; they include no third-party
fonts or images. The prompt templates in `defaults/`, `system_prompts/`, and
`system_prompts_vision/` are part of PWLP and are covered by the MIT License.
