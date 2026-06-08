# Quinten Kocian's Technical Projects List

## Southwest Research Institute (SwRI) Projects

I serve as an embedded systems and signal processing engineer, leading or contributing to projects involving firmware development, hardware/software integration, acoustic and audio system design, real-time DSP implementation, and technical research. My role typically spans system architecture, implementation, testing, and cross-functional collaboration to deliver practical engineering solutions.

---

### Non-Line-of-Sight Imaging with Acoustic Waves, 14-R6222

tags: most interesting project

links: https://www.swri.org/what-we-do/internal-research-development/2022/electronicsautomation/non-line-of-sight-imaging-acoustic-waves-14-r6222

**Role:**
Served as a Principal Investigator and key technical contributor, exploring fundamentals of NLOS acoustic imaging.

**Project Details:**
This project investigated the use of acoustic (sound) waves to image objects that are outside a direct line of sight — essentially "seeing around corners" without optical sensors. Traditional non-line-of-sight (NLOS) imaging relies on expensive pulsed laser and time-resolved photodetector systems; acoustic-based approaches offer a dramatically lower-cost alternative that can capture hidden 3D geometry at longer ranges and with shorter acquisition times.

The research drew on wave-propagation physics and signal processing techniques (such as those used in seismic and radar imaging) to reconstruct the position and shape of hidden objects from reflected acoustic signals. SwRI's broader acoustics and ultrasonics division brings deep expertise in ultrasonic experiments, sound measurement, and acoustic evaluations across applications ranging from defense and autonomous systems to structural inspection.

**Key Applications:**
- Robotic and machine vision (autonomous vehicle navigation around obstacles)
- Remote sensing and surveillance
- Medical imaging
- Defense/stealth applications where active optical sensors are undesirable

---

### Real-time audio filtering using ARM Core M7 and Vesper MEMS smart microphone

tags: most technically challenging project

**Role:**
Led development of the real-time audio filtering system, overseeing hardware integration, DSP implementation, and user-interface design for the STM32F7 and Vesper MEMS microphone platform. I also developed the MATLAB-based filter design workflow that enabled custom equalizer creation and deployment within the ARM CMSIS-DSP framework.

- Perform hardware configuration of the STM32F7 Discovery board using the provided HAL library.
- Perform hardware configuration of Wolfson WM8994 audio codec using the provided BSP library.
- Design and program a user-interface for controlling audio I/O and the implemented equalizer (using on-board touch screen).
- Implement DSP functions (from ARM CMSIS DSP library) and the flow of audio I/O. The filters used here were biquad cascade direct-form II transposed IIR filters with 32-bit floating point arithmetic.
- Design and program a MATLAB script to allow the designer to create custom filter banks (including graphic or parametric equalizers) and get the filter coefficients in the proper format for the ARM CMSIS DSP framework.

**Project Details:**
This project involved the integration of a Vesper MEMS smart microphone with the STM32F7 Discovery board. The goal of this project was to create real-time, custom filtered audio input/output using the ARM CMSIS DSP library for processing. In short, audio would be captured by the smart microphone, processed by the MCU (using ARM CMSIS DSP framework), then output to an unknown medium. The Discovery board would be used not only to process the audio signal, but also to implement a user-interface which gives the user control over a custom designed equalizer.

The design of the equalizer (and the filter coefficients) was done in MATLAB. Possible filters included Butterworth, Chebyshev Type I/II, and Elliptic. These filters were fully customizable, allowing the user to choose center frequency, quality factor, bandwidth, stopband/passband ripple etc. For more standard graphic equalizers, the ANSI S1.11-2004 specification was used for center frequencies. The user could also choose what fractional-octave band spacing was desired.

**Hardware:**
- STM32F7 Discovery board (STM32F746NGH6U MCU) with onboard Wolfson WM8994 audio codec and LCD touch screen. Contains ARM Core M7.
  - Alternative: H743ZI2 Nucleo board (STM32H743ZIT6U MCU)
- Vesper S-VM1010-C smart microphone
- Audio Precision acoustic anechoic chamber for performing I/O characterization and validating filter performance

**Software:**
- STM32CubeIDE
- Board support package (BSP) and hardware abstraction layer (HAL) libraries
- MATLAB filter design tools

**Programming languages:**
- C, ARM CMSIS DSP library
- MATLAB scripting (DSP toolbox, signal processing toolbox)

---

### Sound Pressure Level Meter using Microsoft Surface, TASCAM iXR, and Compiled MATLAB

**Role:**
Led development of a portable sound pressure level monitoring solution, overseeing application design, signal-processing implementation, and system integration across the Microsoft Surface and TASCAM iXR audio interface. I developed the MATLAB-based GUI and SPL processing pipeline, implemented calibration and logging features, and drove testing to deliver a practical field-ready measurement tool.

- Use MATLAB to create GUI and underlying processes: microphone calibration, audio acquisition, sound pressure level (SPL) calculations, and application flow control.
- Apply algorithms/formulas for time-weighted, max time-weighted, peak, and equivalent-continuous SPL to calculate input audio on a frame-by-basis.

**Project Details:**
This project involved designing a custom sound pressure level monitoring and logging application built on top of the Matlab runtime. The resulting application was implemented using the Matlab compiler and targeted for a Microsoft Surface. Additionally, a TASCAM iXR audio interface was used as the audio interface. This project was implemented with a custom housing for the Microsoft surface, TASCAM iXR, and other included sound gear (microphones, calibrator, cables etc.) The goal was to provide a complete sound pressure level monitoring solution in a portable form factor.

The capabilities of the application included:
- Acquire audio and process input into frequency bins, displaying the sound pressure level of various frequency bands as well as total sound pressure level.
- Provide customizable hardware configuration to account for various audio interfaces (sampling rate, bit-depth, frame size).
- Provide custom settings for the sound pressure level meter and visualization.
- Provide calibration and logging features for saving measurements across all frequency bands.
- Provide persistence so the user may continue past sessions or reuse past configurations.

**Hardware:**
- Microsoft Surface Pro
- TASCAM iXR audio interface

**Software:**
- MATLAB

**Programming:**
- MATLAB scripting (audio toolbox)

**Key Applications:**
- Measuring sound leakage of secure facilities to characterize eavesdropping risks

---

### Wireless receiver firmware/software design using LoRa sub-GHZ SoC

**Role:**
Led development of the low-power wireless receiver, overseeing firmware architecture, radio state-machine design, and system-level validation for the LoRa sub-GHz SoC platform. I implemented the timing and power-management firmware, established reliable radio control and watchdog recovery mechanisms, and supported hardware miniaturization and power/RF design validation to deliver a compact, ultra-low-power receiver solution.

- Create timing and configuration firmware for intermittently waking up and putting to sleep the STM32WL55 MCU
- Create a state machine for controlling radio modes of operation when awake (sleep, transmit, receive, Rx failed, Tx failed, etc.)
- Implement independent watchdog for timed reset in case of firmware failure
- Perform size minimization feasibility testing. In other words, how small can we make it without it breaking?
- Perform circuit design validation for power supply design (LDO) and RF design

**Project Details:**
This project involved the design of a low-power wireless receiver which wakes up at intermittent intervals to check for transmissions from a master transmitter. This receiver was integrated into a larger system for the purpose of switching on and off higher load bearing electronics upon a wireless signal from the master receiver. This project involved work in the software application layer, the firmware level (peripheral config), and hardware level. The goal of this project was to create an ultra-low power and small size radio receiver. Reducing the overall size involved the minimization of circuit size by stripping away functionality (such as the Tx path). This project also exposed me to the basics of power system design, albeit from a very high-level vantage point, through circuit/design verification.

**Hardware:**
- NUCLEO-WL55JC2 development board (STM32WL55JC2 MCU)

**Software:**
- STM32CubeIDE
- Board support package (BSP) and hardware abstraction layer (HAL) libraries

**Programming:**
- C

---

### Power System Research and Design for Embedded MCUs

**Role:**
Led research and evaluation of high-efficiency power conversion solutions for embedded MCU systems, driving component selection, performance characterization, and design tradeoff analysis for both AC-DC and DC-DC stages. I collaborated on evaluation board modifications, validated regulation and efficiency across operating conditions, and helped shape a compact, low-standby-power architecture aligned with system constraints.

**Project Details:**
Using various online design tools, I identified candidate power supplies and evaluation boards that would meet the following requirements:
- Minimal package size and pinout
- No step-down or isolation transformers i.e. no flyback topology
- Maintain maximal conversion efficiency for converting wide input range of 85-300 VRMS to 3.3 VDC

Once I identified suitable candidates, I characterized their performance in terms of line regulation, load regulation, and conversion efficiency based on various load conditions. Selecting a suitable candidate then led to research into an ultra-high efficiency DC-DC converter for maintaining very tight load regulation. I not only performed the part selection, but collaborated with technical staff to alter evaluation board components in accordance with the above constraints. For example, we tested various output voltages on the primary side by altering the configuration of the SMPS feedback path. For the buck topology we were using, this was done by changing the values of a simple resistor divider. In addition, I evaluated the tradeoff between output voltage swing at very low or no-load conditions and standby current consumption. In short, a bleed resistor was needed at the output of the SMPS to prevent large voltage swings during no-load conditions. This leads to standby current consumption at no-load conditions, but decreases maximum output voltage. Since we had a fairly robust secondary DC-DC converter, we could sacrifice some extra voltage swing at the output of the primary converter to achieve a much lower standby current at no-load conditions.

**Equipment & Instrumentation:**
- BK Precision programmable DC electronic load
- Programmable AC power supply
- DC power supply and multimeter

---

## University of Texas at San Antonio (UTSA) Projects

### Integration of PIC16 MCU with GSM Module

**Role:**
Contributed to the embedded system design and integration of a PIC16-based temperature alert device, focusing on MCU-to-GSM communication, interrupt-driven firmware behavior, and command/response control over a USART interface. I helped implement the logic for issuing AT commands, handling GSM response parsing, and supporting the end-to-end alert workflow that delivered temperature warnings through the Hologram IoT network.

**Project Details:**
This project was related to my Microcomputers course in which students learned basic embedded systems concepts such as basic Assembly and C programming. As a part of this project, we worked as a team to integrate a PIC16 microcontroller with a GSM module to alert a user of high-temperature conditions in an arbitrary environment. The MCU was interfaced with the GSM module via a USART interface using AT+commands to instruct the GSM module what to do. The SIM card was sourced from Hologram IoT, which also provides a backend cloud interface to perform application-level functions such as API development.

The operation of the system is as follows:
- The PIC16 would trigger a warning event upon a situation in which the ambient temperature rose above a predetermined setpoint.
- The PIC16 would send a sequence of AT+commands to the GSM module instructing it to open a TCP/IP connection with the Hologram IoT server, with accompanying "event" data encoded as JSON.
- The Hologram IoT server was configured to receive and parse the data from the GSM module and send a text message to a preconfigured phone number.

The largest challenge in this project was learning how to efficiently program the PIC16 MCU to interrupt upon receiving response frames from the GSM module and parsing the data accordingly to generate the correct sequence of responses. This process was done with what turned out to be a simple state machine that terminated upon the reception of a complete AT+command response from the GSM module.

**Hardware:**
- PIC16F1829 MCU by Microchip
- Generic GSM Module
- Hologram IoT SIM card
- Generic LCD module
- Generic thermistor

**Software:**
- MPLab X IDE

**Programming:**
- C

---

### Senior Design Project – Low-Volume Chicken Seasoning Machine (ChickenMaxx 9000)

tags: project I'm most proud of, most complicated project

**Role:**
Led the electrical engineering effort for a sponsored senior design project, directing system design, cross-functional coordination, customer communication, and design review for a low-volume automated seasoning machine prototype. I oversaw the electrical architecture supporting conveyor, vibration, and power-drive systems, contributed to the build and integration process, and helped deliver an award-winning prototype recognized at the UTSA Technology Symposium.

**Project Details:**
This was a funded and sponsored project by HEB. It involved the design of a low-volume chicken seasoning machine prototype. The design distributed seasoning from an elevated-bin hopper via a vibrator plate to a conveyor system underneath. The power system was 480V, 3-phase to power the VFD, conveyor motors, and bin-hopper vibrator.

The project team consisted of two sub-teams, a mechanical and an electrical team, demonstrating cross-functional collaboration and design. As the leader of the electrical team, it was my job to supervise and lead the design, maintain customer communications, approve and review designs, and participate in the build process. Project materials available on request.

The result of this project was winning first overall at the Fall 2021 UTSA Technology Symposium, and a cash prize for the team.
