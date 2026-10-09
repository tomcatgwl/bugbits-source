# Independent native byte kernels

These original GDScript implementations accept caller-owned byte arrays. They
contain no game images, geometry, captured frames, memory dumps, executable bytes,
or original game data. They are covered by the repository's MIT license.

- `kernels/temporal_blur.gd`: bounded, stateful three-channel temporal blending
  and separable spatial filtering. Input uses tight four-byte pixels; output alpha
  is 255. The next history is the filtered output, with copied state ownership.
- `kernels/pixel_center_copy.gd`: fixed 1024×768 to 128×128 pixel-center linear
  downsampling on encoded bytes. It preserves channel order and processes alpha
  independently; it does not convert color spaces.

No original game assets are needed for the synthetic tests. With a Godot 4
executable available, run from the repository root:

```sh
godot --headless --path native --script res://tests/test_kernels.gd
```

The runner checks integer truncation, state ownership, invalid inputs, borders,
an independently specified impulse response, channel handling and sample
coordinates. A deliberate incorrect expectation must produce a nonzero exit:

```sh
godot --headless --path native --script res://tests/test_kernels.gd -- --negative-expected
```

These tests cover byte processing only. They do not verify the original game's
complete rendering, animation, occlusion, timing or gameplay. The full native
prototype and private original-runtime evidence are not included.

## Reentrant lifetime metadata

`support/release_guard.h` is original C bookkeeping for nested release callbacks.
It never accesses the observed object, invokes a release method, or owns a
reference. A nested terminal return marks the generation; retirement is deferred
until the outermost call completes. The owner must initialize metadata before
publication, maintain object/slot lifetime, and stop reusing retired generations.

The intended contract is a single owner with synchronous reentry. Atomic fields
do not supply a concurrent object registry or prove safety for overlapping
destruction, generation reuse, or arbitrary COM implementations. Depth and event
limits, underflow, and a nonzero return after a terminal return set sticky unknown
flags. The last case can also arise from legitimate concurrent completion order;
it is a conservative refusal, not proof of an object implementation defect.

With a C11 compiler supporting GCC-style atomic builtins, run these synthetic
checks from the repository root (all outputs stay in the project):

```sh
mkdir -p out/native-checks
cc -std=c11 -Wall -Wextra -Werror -I native/support native/tests/test_release_guard.c -o out/native-checks/test_release_guard
out/native-checks/test_release_guard
```

`out/native-checks/test_release_guard --negative-expected` deliberately expects
early retirement and must exit 1. Unknown options exit 2. These checks require no
game assets, Wine, graphics server, or original runtime observations. They test
metadata sequences only; they cannot establish game fidelity or general COM
lifecycle safety. No observer hooks, DLLs, disassembly or private captures are
included.
