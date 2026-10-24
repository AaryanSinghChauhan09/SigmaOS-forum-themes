    # SigmaOS-forum-themes

    Community forum theme pack

    Part of the **SigmaOS** sovereign operating-system ecosystem — a multi-repository
    distribution modelled on Linux Mint and Omarchy Linux. See the parent
    [`SigmaOS`](https://github.com/AaryanSinghChauhan09/SigmaOS) repository for the
    full component index.

    ## Upstream inspirations
    - https://github.com/linuxmint/forums-theme

    ## Design principles applied
    - **Abstraction**
- **Plan Before Act**
- **Fail-Fast**
- **Defensive Programming**
- **KISS**
- **Deterministic Testing**

    ## Usage
    Verbs: `themes, apply-plan, preview, export`

    ```
    $ sigma-forum-themes themes ./pack
sigma-dark   Sigma Dark    dark    discourse
sigma-light  Sigma Light   light   flarum
$ sigma-forum-themes apply-plan ./pack sigma-dark --root /var/discourse --backend discourse
copy stylesheets/sigma-dark.css -> /var/discourse/stylesheets/sigma-dark.css
$ sigma-forum-themes preview ./pack sigma-dark --out /tmp/preview.html
$ sigma-forum-themes export ./pack sigma-dark --out sigma-dark.tar.gz

    ```

    ## Build & test
    ```
    make build
    make test
    ```

    ## Licence
    GNU General Public License v3.0 (FOSS).
