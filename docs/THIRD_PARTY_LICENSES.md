# Third-party license notes

This repository distributes source and an integration patch, not bundled runtimes
or dependency wheels. Install dependencies separately from their official sources
and preserve the license files shipped with them. The following versions match the
pinned upstream backend lock used for the tests.

| Dependency | Version | License | Authoritative text |
| --- | --- | --- | --- |
| Presenton source | 0.9.11-beta / e158a014 | Apache-2.0 | Included LICENSE and upstream NOTICE |
| python-pptx | 1.0.2 | MIT | https://raw.githubusercontent.com/scanny/python-pptx/v1.0.2/LICENSE |
| XlsxWriter | 3.2.9 | BSD-2-Clause | https://raw.githubusercontent.com/jmcnamara/XlsxWriter/RELEASE_3.2.9/LICENSE.txt |
| lxml | 6.1.1 | BSD-3-Clause | https://raw.githubusercontent.com/lxml/lxml/lxml-6.1.1/LICENSE.txt |
| Pillow | 12.2.0 | MIT-CMU | https://raw.githubusercontent.com/python-pillow/Pillow/12.2.0/LICENSE |
| typing_extensions | 4.15.0 | PSF-2.0 and included historical text | https://raw.githubusercontent.com/python/typing_extensions/4.15.0/LICENSE |

The preserved upstream NOTICE is not a complete SBOM and has version omissions;
this supplemental inventory does not claim all of Presenton's dependencies are
Apache-2.0. Building an image or desktop installer is a separate redistribution
review, including bundled fonts, images, native libraries and LGPL/MPL obligations.

The separately distributed Presenton export-core 1.0.34 package did not contain a
LICENSE file or package license field in the version audited. This project neither
copies nor redistributes it and does not alter its low/high-quality controls.
