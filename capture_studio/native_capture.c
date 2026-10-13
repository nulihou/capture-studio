/* Native camera producer: framed JPEG with V4L2 timestamps; no decoding/inference.
 * Build: gcc -O2 -std=c11 -Wall -Wextra v4l2_mode_probe.c -o v4l2_mode_probe
 * Run: ./v4l2_mode_probe --source-format raw --manual-exposure 100 --duration-sec 20 --output-json run.json
 * S_FMT requested MJPG/YUYV640x480 and S_PARM30 are intentional: this camera may not stream
 * if opened without negotiating a format first. G_FMT/G_PARM report actual values.
 */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <time.h>
#include <linux/videodev2.h>
#include <math.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>

#define MAX_RECORDS 32768
#define MAX_BUFFERS 64
#define CONTROL_COUNT 4

static volatile sig_atomic_t stop_signal = 0;
static void request_stop(int signum) { stop_signal = signum; }

static const uint32_t control_ids[CONTROL_COUNT] = {
    V4L2_CID_EXPOSURE_AUTO, V4L2_CID_EXPOSURE_ABSOLUTE,
    V4L2_CID_EXPOSURE_AUTO_PRIORITY, V4L2_CID_POWER_LINE_FREQUENCY};
static const char *control_names[CONTROL_COUNT] = {
    "exposure_auto", "exposure_absolute", "exposure_auto_priority", "power_line_frequency"};
struct controls_snapshot {
    bool taken;
    int value[CONTROL_COUNT], error[CONTROL_COUNT];
    int64_t observed_ns;
};

struct mapping { void *address; size_t size; };
struct record {
    int64_t arrival_ns, timestamp_ns;
    uint32_t sequence, bytes, flags;
};
struct stats {
    size_t count, record_count, valid_timestamp_count;
    uint64_t bytes, sequence_gaps, sequence_duplicates, sequence_backwards;
    uint64_t timestamp_duplicates, timestamp_backwards, invalid_timestamps;
    uint64_t error_flag_buffers, timestamp_monotonic, timestamp_copy, timestamp_unknown;
    int64_t first_arrival, last_arrival, first_timestamp, last_timestamp;
    uint32_t first_sequence, last_sequence;
    struct record *records;
};

static int xioctl(int fd, unsigned long request, void *argument) {
    int result;
    do { result = ioctl(fd, request, argument); } while (result < 0 && errno == EINTR);
    return result;
}

static int64_t monotonic_ns(void) {
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) < 0) return -1;
    return (int64_t)now.tv_sec * INT64_C(1000000000) + now.tv_nsec;
}

static void json_string(FILE *file, const char *value) {
    fputc('"', file);
    for (const unsigned char *cursor = (const unsigned char *)value; *cursor; ++cursor) {
        if (*cursor == '"' || *cursor == '\\') { fputc('\\', file); fputc(*cursor, file); }
        else if (*cursor < 32) fprintf(file, "\\u%04x", *cursor);
        else fputc(*cursor, file);
    }
    fputc('"', file);
}

static double span_hz(size_t count, int64_t first, int64_t last) {
    return count >= 2 && last > first ? (double)(count - 1) * 1e9 / (double)(last - first) : NAN;
}

static void json_number(FILE *file, double value) {
    if (isfinite(value)) fprintf(file, "%.9f", value); else fputs("null", file);
}

static int snapshot_controls(int fd, struct controls_snapshot *snapshot) {
    snapshot->taken = true;
    snapshot->observed_ns = monotonic_ns();
    int first_error = 0;
    for (int index = 0; index < CONTROL_COUNT; ++index) {
        struct v4l2_control control = {.id = control_ids[index]};
        if (xioctl(fd, VIDIOC_G_CTRL, &control) < 0) {
            snapshot->error[index] = errno;
            if (!first_error) first_error = errno;
        } else {
            snapshot->value[index] = control.value;
            snapshot->error[index] = 0;
        }
    }
    if (first_error) { errno = first_error; return -1; }
    return 0;
}

static int set_control(int fd, int index, int value) {
    struct v4l2_control control = {.id = control_ids[index], .value = value};
    return xioctl(fd, VIDIOC_S_CTRL, &control);
}

static bool same_controls(const struct controls_snapshot *first, const struct controls_snapshot *second) {
    if (!first->taken || !second->taken) return false;
    for (int index = 0; index < CONTROL_COUNT; ++index) {
        if (first->error[index] || second->error[index] || first->value[index] != second->value[index]) return false;
    }
    return true;
}

static void json_controls(FILE *file, const struct controls_snapshot *snapshot) {
    if (!snapshot->taken) { fputs("null", file); return; }
    fprintf(file, "{\"observed_monotonic_ns\": %lld", (long long)snapshot->observed_ns);
    for (int index = 0; index < CONTROL_COUNT; ++index) {
        fprintf(file, ", \"%s\": {\"value\": ", control_names[index]);
        if (!snapshot->error[index]) fprintf(file, "%d", snapshot->value[index]); else fputs("null", file);
        fprintf(file, ", \"errno\": %d}", snapshot->error[index]);
    }
    fputc('}', file);
}

static void record_buffer(struct stats *stats, const struct v4l2_buffer *buffer, int64_t arrival) {
    int64_t timestamp = -1;
    if (buffer->timestamp.tv_sec >= 0 && buffer->timestamp.tv_usec >= 0 &&
        buffer->timestamp.tv_usec < 1000000) {
        timestamp = (int64_t)buffer->timestamp.tv_sec * INT64_C(1000000000) +
                    (int64_t)buffer->timestamp.tv_usec * 1000;
        if (timestamp == 0) timestamp = -1;
    }
    if (stats->count == 0) {
        stats->first_arrival = arrival;
        stats->first_sequence = buffer->sequence;
    } else {
        /* Signed modular difference handles uint32 kernel sequence wrap. */
        int32_t difference = (int32_t)(buffer->sequence - stats->last_sequence);
        if (difference > 1) stats->sequence_gaps += (uint32_t)difference - 1;
        else if (difference == 0) ++stats->sequence_duplicates;
        else if (difference < 0) ++stats->sequence_backwards;
    }
    stats->last_arrival = arrival;
    stats->last_sequence = buffer->sequence;
    if (timestamp < 0) ++stats->invalid_timestamps;
    else {
        if (!stats->valid_timestamp_count) stats->first_timestamp = timestamp;
        else {
            stats->timestamp_duplicates += timestamp == stats->last_timestamp;
            stats->timestamp_backwards += timestamp < stats->last_timestamp;
        }
        stats->last_timestamp = timestamp;
        ++stats->valid_timestamp_count;
    }
    uint32_t clock_type = buffer->flags & V4L2_BUF_FLAG_TIMESTAMP_MASK;
    stats->timestamp_monotonic += clock_type == V4L2_BUF_FLAG_TIMESTAMP_MONOTONIC;
    stats->timestamp_copy += clock_type == V4L2_BUF_FLAG_TIMESTAMP_COPY;
    stats->timestamp_unknown += clock_type == V4L2_BUF_FLAG_TIMESTAMP_UNKNOWN;
    stats->error_flag_buffers += !!(buffer->flags & V4L2_BUF_FLAG_ERROR);
    ++stats->count;
    stats->bytes += buffer->bytesused;
    if (stats->record_count < MAX_RECORDS) {
        stats->records[stats->record_count++] = (struct record){
            arrival, timestamp, buffer->sequence, buffer->bytesused, buffer->flags};
    }
}

static void usage(const char *program) {
    fprintf(stderr, "Usage: %s --output-json PATH [--device /dev/video0] [--duration-sec 20] "
                    "[--warmup-sec 2] [--sample-jpeg PATH] --manual-exposure INTEGER "
                    "[--power-line-frequency 0|1|2] [--source-format mjpeg|raw]\n", program);
}

int main(int argc, char **argv) {
    const char *device = "/dev/video0", *output_path = NULL, *sample_path = NULL;
    double duration = 20, warmup = 2;
    int manual_exposure = -1; int requested_mode = V4L2_EXPOSURE_MANUAL;
    uint32_t requested_fourcc = V4L2_PIX_FMT_MJPEG;
    int power_line_requested = -1;
    for (int index = 1; index < argc; index += 2) {
        if (!strcmp(argv[index], "--help")) { usage(argv[0]); return 0; }
        if (index + 1 >= argc) { usage(argv[0]); return 2; }
        if (!strcmp(argv[index], "--device")) device = argv[index + 1];
        else if (!strcmp(argv[index], "--output-json")) output_path = argv[index + 1];
        else if (!strcmp(argv[index], "--sample-jpeg")) sample_path = argv[index + 1];
        else if (!strcmp(argv[index], "--source-format")) {
            if (!strcmp(argv[index + 1], "raw")) requested_fourcc = V4L2_PIX_FMT_YUYV;
            else if (strcmp(argv[index + 1], "mjpeg")) { usage(argv[0]); return 2; }
        }
        else if (!strcmp(argv[index], "--exposure-mode")) { requested_mode = atoi(argv[index+1]); if (requested_mode < 0 || requested_mode > 2) return 2; }
        else if (!strcmp(argv[index], "--manual-exposure")) {
            char *tail;
            errno = 0;
            long value = strtol(argv[index + 1], &tail, 10);
            if (!*argv[index + 1] || *tail || errno || value <= 0 || value > 10000) { usage(argv[0]); return 2; }
            manual_exposure = (int)value;
        }
        else if (!strcmp(argv[index], "--power-line-frequency")) {
            char *tail;
            errno = 0;
            long value = strtol(argv[index + 1], &tail, 10);
            if (!*argv[index + 1] || *tail || errno || value < 0 || value > 2) { usage(argv[0]); return 2; }
            power_line_requested = (int)value;
        }
        else if (!strcmp(argv[index], "--duration-sec") || !strcmp(argv[index], "--warmup-sec")) {
            char *tail;
            double value = strtod(argv[index + 1], &tail);
            if (*tail || !isfinite(value)) { usage(argv[0]); return 2; }
            if (!strcmp(argv[index], "--duration-sec")) duration = value; else warmup = value;
        } else { usage(argv[0]); return 2; }
    }
    if (!output_path || manual_exposure <= 0 || !(duration > 0 && duration <= 86400 && warmup >= 0 && warmup <= 30)) {
        usage(argv[0]); return 2;
    }
    if (sample_path && requested_fourcc != V4L2_PIX_FMT_MJPEG) {
        fputs("--sample-jpeg requires MJPEG; raw buffer must not be mislabeled JPEG\n", stderr);
        return 2;
    }
    if (sample_path && !strcmp(output_path, sample_path)) {
        fputs("Report and sample paths must differ\n", stderr); return 2;
    }
    /* Reserve report before touching the camera; prior evidence cannot be overwritten. */
    int output_fd = open(output_path, O_WRONLY | O_CREAT | O_EXCL, 0666);
    if (output_fd < 0) { perror("open exclusive output JSON"); return 2; }
    FILE *output = fdopen(output_fd, "w");
    if (!output) { perror("fdopen output"); close(output_fd); return 2; }
    int sample_fd = -1;
    if (sample_path) {
        sample_fd = open(sample_path, O_WRONLY | O_CREAT | O_EXCL, 0666);
        if (sample_fd < 0) { perror("open exclusive sample JPEG"); fclose(output); return 2; }
    }
    struct mapping mappings[MAX_BUFFERS] = {0};
    struct stats stats = {0};
    struct v4l2_format format = { .type = V4L2_BUF_TYPE_VIDEO_CAPTURE };
    struct v4l2_streamparm streamparm = { .type = V4L2_BUF_TYPE_VIDEO_CAPTURE };
    struct v4l2_capability capability = {0};
    unsigned int mapping_count = 0;
    int fd = -1, saved_errno = 0;
    bool streaming = false, complete = false, cleanup_ok = true;
    const char *stage = NULL;
    int64_t begin_ns = 0, end_ns = 0, stop_ns = 0;
    size_t warmup_buffers = 0, sample_size = 0, sample_capacity = 0;
    unsigned char *sample_data = NULL;
    uint32_t sample_sequence = 0;
    int64_t sample_timestamp = -1;
    struct controls_snapshot before = {0}, after_streamon_set = {0}, after_measurement = {0},
                             after_streamoff = {0}, restored = {0};
    bool original_controls_valid = false, exposure_verified_before = false, exposure_verified_after = false;
    bool power_line_verified_before = false, power_line_verified_after = false;
    bool restore_attempted = false, restore_verified = false;
    int restore_manual_errno = 0, restore_absolute_errno = 0, restore_auto_errno = 0;
    int restore_priority_errno = 0, restore_frequency_errno = 0, restore_read_errno = 0;
    struct sigaction action = {0};
    action.sa_handler = request_stop;
    sigemptyset(&action.sa_mask);
    sigaction(SIGINT, &action, NULL);
    sigaction(SIGTERM, &action, NULL);
    signal(SIGPIPE, SIG_IGN);
#define FAIL(description) do { stage = (description); saved_errno = errno ? errno : EIO; goto cleanup; } while (0)
    stats.records = calloc(MAX_RECORDS, sizeof(*stats.records));
    if (!stats.records) FAIL("allocate bounded records");
    fd = open(device, O_RDWR | O_NONBLOCK);
    if (fd < 0) FAIL("open camera");
    if (snapshot_controls(fd, &before) < 0) FAIL("GET original exposure/priority/power-line controls");
    original_controls_valid = true;
    if (xioctl(fd, VIDIOC_QUERYCAP, &capability) < 0) FAIL("VIDIOC_QUERYCAP");
    uint32_t capabilities = capability.capabilities & V4L2_CAP_DEVICE_CAPS ?
                            capability.device_caps : capability.capabilities;
    if (!(capabilities & V4L2_CAP_VIDEO_CAPTURE) || !(capabilities & V4L2_CAP_STREAMING)) {
        errno = ENOTSUP; FAIL("camera requires single-plane capture and streaming");
    }
    format.fmt.pix.width = 640;
    format.fmt.pix.height = 480;
    format.fmt.pix.pixelformat = requested_fourcc;
    format.fmt.pix.field = V4L2_FIELD_ANY;
    if (xioctl(fd, VIDIOC_S_FMT, &format) < 0) FAIL("VIDIOC_S_FMT requested MJPG/YUYV640x480");
    if (xioctl(fd, VIDIOC_G_FMT, &format) < 0) FAIL("VIDIOC_G_FMT");
    if (format.fmt.pix.width != 640 || format.fmt.pix.height != 480 ||
        format.fmt.pix.pixelformat != requested_fourcc) {
        errno = EINVAL; FAIL("negotiated format is not requested MJPG/YUYV640x480");
    }
    streamparm.parm.capture.timeperframe.numerator = 1;
    streamparm.parm.capture.timeperframe.denominator = 30;
    if (xioctl(fd, VIDIOC_S_PARM, &streamparm) < 0) FAIL("VIDIOC_S_PARM30");
    if (xioctl(fd, VIDIOC_G_PARM, &streamparm) < 0) FAIL("VIDIOC_G_PARM");
    struct v4l2_requestbuffers request = {
        .count = 4, .type = V4L2_BUF_TYPE_VIDEO_CAPTURE, .memory = V4L2_MEMORY_MMAP};
    if (xioctl(fd, VIDIOC_REQBUFS, &request) < 0) FAIL("VIDIOC_REQBUFS");
    if (request.count < 2 || request.count > MAX_BUFFERS) {
        errno = EINVAL; FAIL("invalid returned mmap buffer count");
    }
    for (unsigned int index = 0; index < request.count; ++index) {
        struct v4l2_buffer buffer = {
            .type = V4L2_BUF_TYPE_VIDEO_CAPTURE, .memory = V4L2_MEMORY_MMAP, .index = index};
        if (xioctl(fd, VIDIOC_QUERYBUF, &buffer) < 0) FAIL("VIDIOC_QUERYBUF");
        void *address = mmap(NULL, buffer.length, PROT_READ | PROT_WRITE, MAP_SHARED, fd, buffer.m.offset);
        if (address == MAP_FAILED) FAIL("mmap camera buffer");
        mappings[index] = (struct mapping){address, buffer.length};
        ++mapping_count;
        if (xioctl(fd, VIDIOC_QBUF, &buffer) < 0) FAIL("VIDIOC_QBUF initial");
    }
    enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (xioctl(fd, VIDIOC_STREAMON, &type) < 0) FAIL("VIDIOC_STREAMON");
    streaming = true;
    /* Camera format/start operations may reset controls; establish the condition only now. */
    if (power_line_requested >= 0 && set_control(fd, 3, power_line_requested) < 0)
        FAIL("SET requested power-line frequency after STREAMON");
    if (requested_mode != V4L2_EXPOSURE_AUTO) {
        if (set_control(fd, 0, V4L2_EXPOSURE_MANUAL) < 0) FAIL("SET seed manual mode");
        if (set_control(fd, 1, manual_exposure) < 0) FAIL("SET exposure absolute after STREAMON");
    }
    if (set_control(fd, 0, requested_mode) < 0) FAIL("SET final exposure mode after seed exposure");
    if (snapshot_controls(fd, &after_streamon_set) < 0) FAIL("GET controls after STREAMON+SET");
    exposure_verified_before = after_streamon_set.value[0] == requested_mode &&
                               (requested_mode == V4L2_EXPOSURE_AUTO || after_streamon_set.value[1] == manual_exposure);
    if (!exposure_verified_before) { errno = EPROTO; FAIL("manual exposure readback mismatch: measurement not started"); }
    if (power_line_requested >= 0) {
        power_line_verified_before = after_streamon_set.value[3] == power_line_requested;
        if (!power_line_verified_before) { errno = EPROTO; FAIL("power-line frequency readback mismatch: measurement not started"); }
    }
    if (stop_signal) { errno = EINTR; FAIL("signal before measurement"); }
    int64_t now = monotonic_ns();
    if (now < 0) FAIL("clock_gettime");
    begin_ns = now + (int64_t)(warmup * 1e9);
    end_ns = begin_ns + (int64_t)(duration * 1e9);
    for (;;) {
        if (stop_signal) { complete = stats.count >= 2; goto cleanup; }
        now = monotonic_ns();
        if (now < 0) FAIL("clock_gettime");
        if (now >= end_ns) { complete = true; break; }
        int timeout_ms = (int)((end_ns - now + 999999) / 1000000);
        if (timeout_ms > 200) timeout_ms = 200;
        struct pollfd poll_fd = {.fd = fd, .events = POLLIN};
        int ready = poll(&poll_fd, 1, timeout_ms);
        if (ready < 0) { if (errno == EINTR) continue; FAIL("poll camera"); }
        if (!ready) continue;
        if (poll_fd.revents & (POLLERR | POLLHUP | POLLNVAL)) {
            errno = EIO; FAIL("camera poll error/hangup");
        }
        while (monotonic_ns() < end_ns) {
            if (stop_signal) { complete = stats.count >= 2; goto cleanup; }
            struct v4l2_buffer buffer = {.type = V4L2_BUF_TYPE_VIDEO_CAPTURE, .memory = V4L2_MEMORY_MMAP};
            if (xioctl(fd, VIDIOC_DQBUF, &buffer) < 0) {
                if (errno == EAGAIN) break;
                FAIL("VIDIOC_DQBUF");
            }
            int64_t arrival = monotonic_ns();
            if (arrival < 0) FAIL("clock_gettime");
            if (buffer.index >= mapping_count || buffer.bytesused > mappings[buffer.index].size) {
                errno = EOVERFLOW; FAIL("invalid DQBUF index/bytesused");
            }
            if (arrival >= begin_ns && arrival < end_ns) {
                record_buffer(&stats, &buffer, arrival);
                if(stats.invalid_timestamps || stats.timestamp_duplicates || stats.timestamp_backwards || buffer.flags & V4L2_BUF_FLAG_ERROR) {errno=EPROTO; FAIL("invalid native frame/timestamp");}
                uint64_t stamp=(uint64_t)stats.last_timestamp;
                uint32_t length=buffer.bytesused;
                if (fwrite(&stamp,8,1,stdout)!=1 || fwrite(&length,4,1,stdout)!=1 || fwrite(mappings[buffer.index].address,1,length,stdout)!=length || fflush(stdout)!=0) FAIL("native frame pipe");
                if (sample_fd >= 0 && buffer.bytesused > 0) {
                    if (sample_capacity < buffer.bytesused) {
                        unsigned char *resized = realloc(sample_data, buffer.bytesused);
                        if (!resized) FAIL("allocate final compressed sample");
                        sample_data = resized; sample_capacity = buffer.bytesused;
                    }
                    memcpy(sample_data, mappings[buffer.index].address, buffer.bytesused);
                    sample_size = buffer.bytesused;
                    sample_sequence = buffer.sequence;
                    sample_timestamp = stats.last_timestamp;
                }
            } else if (arrival < begin_ns) ++warmup_buffers;
            if (xioctl(fd, VIDIOC_QBUF, &buffer) < 0) FAIL("VIDIOC_QBUF");
        }
    }
cleanup:
    stop_ns = monotonic_ns();
    if (streaming && !after_streamon_set.taken) {
        /* Preserve actual controls even if either post-start SET failed. */
        snapshot_controls(fd, &after_streamon_set);
    }
    if (fd >= 0 && original_controls_valid) {
        if (snapshot_controls(fd, &after_measurement) < 0) {
            if (!stage) { stage = "GET controls after measurement before STREAMOFF"; saved_errno = errno; }
        } else if (exposure_verified_before) {
            exposure_verified_after = after_measurement.value[0] == requested_mode &&
                                      (requested_mode == V4L2_EXPOSURE_AUTO || after_measurement.value[1] == manual_exposure);
            if (!exposure_verified_after && !stage) {
                stage = "exposure condition changed before STREAMOFF"; saved_errno = EPROTO;
            }
            if (power_line_requested >= 0) {
                power_line_verified_after = after_measurement.value[3] == power_line_requested;
                if (!power_line_verified_after && !stage) {
                    stage = "power-line condition changed before STREAMOFF"; saved_errno = EPROTO;
                }
            }
        }
    }
    if (streaming) {
        enum v4l2_buf_type stop_type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        if (xioctl(fd, VIDIOC_STREAMOFF, &stop_type) < 0) {
            perror("VIDIOC_STREAMOFF cleanup"); cleanup_ok = false;
        }
    }
    if (fd >= 0 && original_controls_valid) {
        if (snapshot_controls(fd, &after_streamoff) < 0) {
            if (!stage) { stage = "GET controls after STREAMOFF"; saved_errno = errno; }
        }
        restore_attempted = true;
        /* Try each recovery step once even if an earlier recovery step fails. No experiment retry. */
        if (set_control(fd, 0, V4L2_EXPOSURE_MANUAL) < 0) restore_manual_errno = errno;
        if (set_control(fd, 1, before.value[1]) < 0) restore_absolute_errno = errno;
        /* Restore other original controls only if stream setup changed them or GET failed. */
        if (after_streamoff.error[2] || after_streamoff.value[2] != before.value[2]) {
            if (set_control(fd, 2, before.value[2]) < 0) restore_priority_errno = errno;
        }
        if (after_streamoff.error[3] || after_streamoff.value[3] != before.value[3]) {
            if (set_control(fd, 3, before.value[3]) < 0) restore_frequency_errno = errno;
        }
        if (set_control(fd, 0, before.value[0]) < 0) restore_auto_errno = errno;
        if (snapshot_controls(fd, &restored) < 0) restore_read_errno = errno;
        restore_verified = same_controls(&before, &restored) && !restore_manual_errno &&
                           !restore_absolute_errno && !restore_auto_errno && !restore_priority_errno &&
                           !restore_frequency_errno && !restore_read_errno;
        if (!restore_verified) {
            cleanup_ok = false;
            fputs("Original camera controls could not be fully restored/readback verified\n", stderr);
        }
    }
    for (unsigned int index = 0; index < mapping_count; ++index) {
        if (munmap(mappings[index].address, mappings[index].size) < 0) { perror("munmap"); cleanup_ok = false; }
    }
    if (fd >= 0 && close(fd) < 0) { perror("close camera"); cleanup_ok = false; }
    bool sample_saved = false;
    if (sample_fd >= 0 && sample_size > 0) {
        size_t written = 0;
        while (written < sample_size) {
            ssize_t amount = write(sample_fd, sample_data + written, sample_size - written);
            if (amount < 0 && errno == EINTR) continue;
            if (amount <= 0) { perror("save final JPEG"); cleanup_ok = false; break; }
            written += (size_t)amount;
        }
        sample_saved = written == sample_size;
    }
    if (sample_fd >= 0 && close(sample_fd) < 0) { perror("close sample"); cleanup_ok = false; }
    double measured_seconds = begin_ns > 0 && stop_ns > begin_ns ?
                              (double)((stop_ns < end_ns ? stop_ns : end_ns) - begin_ns) / 1e9 : 0;
    bool succeeded = complete && stats.count >= 2 && !stage && cleanup_ok &&
                     exposure_verified_before && exposure_verified_after && restore_verified &&
                     (power_line_requested < 0 || (power_line_verified_before && power_line_verified_after));
    fputs("{\n  \"schema\": \"v4l2_exposure_probe_v1\",\n  \"status\": ", output);
    json_string(output, succeeded ? "complete" : "failed_or_incomplete");
    fputs(",\n  \"device\": ", output); json_string(output, device);
    fputs(",\n  \"power_line_frequency_requested\": ", output);
    if (power_line_requested >= 0) fprintf(output, "%d", power_line_requested); else fputs("null", output);
    fputs(",\n  \"power_line_readback_verified_before\": ", output);
    fputs(power_line_requested >= 0 ? (power_line_verified_before ? "true" : "false") : "null", output);
    fputs(",\n  \"power_line_readback_verified_after\": ", output);
    fputs(power_line_requested >= 0 ? (power_line_verified_after ? "true" : "false") : "null", output);
    fputs(",\n  \"manual_exposure_requested\": ", output);
    if (requested_mode == V4L2_EXPOSURE_AUTO) fputs("null", output);
    else fprintf(output, "%d", manual_exposure);
    fprintf(output, ",\n  \"exposure_mode_requested\": %d,\n  \"stop_signal\": %d,\n"
                    "  \"exposure_readback_verified_before\": %s,\n  \"exposure_readback_verified_after\": %s,\n"
                    "  \"control_snapshots\": {\n    \"before\": ", requested_mode, (int)stop_signal,
                    exposure_verified_before ? "true" : "false", exposure_verified_after ? "true" : "false");
    json_controls(output, &before);
    fputs(",\n    \"after_streamon_set\": ", output); json_controls(output, &after_streamon_set);
    fputs(",\n    \"after_measurement_before_streamoff\": ", output); json_controls(output, &after_measurement);
    fputs(",\n    \"after_streamoff\": ", output); json_controls(output, &after_streamoff);
    fputs(",\n    \"restore\": ", output); json_controls(output, &restored);
    fprintf(output, "\n  },\n  \"restoration\": {\"attempted\": %s, \"verified\": %s, "
                    "\"manual_errno\": %d, \"absolute_errno\": %d, \"auto_errno\": %d, "
                    "\"priority_errno\": %d, \"power_line_errno\": %d, \"read_errno\": %d}",
            restore_attempted ? "true" : "false", restore_verified ? "true" : "false",
            restore_manual_errno, restore_absolute_errno, restore_auto_errno,
            restore_priority_errno, restore_frequency_errno, restore_read_errno);
    fprintf(output, ",\n  \"warmup_sec\": %.9f,\n  \"requested_window_sec\": %.9f,\n"
                    "  \"actual_window_sec\": %.9f,\n  \"window_begin_monotonic_ns\": %lld,\n"
                    "  \"window_end_monotonic_ns\": %lld,\n", warmup, duration, measured_seconds,
                    (long long)begin_ns, (long long)end_ns);
    uint32_t fourcc = format.fmt.pix.pixelformat;
    char fourcc_text[5] = {(char)(fourcc & 255), (char)((fourcc >> 8) & 255),
                         (char)((fourcc >> 16) & 255), (char)((fourcc >> 24) & 255), 0};
    fprintf(output, "  \"negotiated_format\": {\"width\": %u, \"height\": %u, \"fourcc\": ",
            format.fmt.pix.width, format.fmt.pix.height); json_string(output, fourcc_text);
    fprintf(output, ", \"sizeimage\": %u, \"bytesperline\": %u},\n"
                    "  \"negotiated_time_per_frame\": {\"numerator\": %u, \"denominator\": %u},\n"
                    "  \"mmap_buffers\": %u,\n  \"ignored_warmup_buffers\": %zu,\n"
                    "  \"buffers\": %zu,\n  \"bytes_total\": %llu,\n  \"whole_window_hz\": ",
            format.fmt.pix.sizeimage, format.fmt.pix.bytesperline,
            streamparm.parm.capture.timeperframe.numerator, streamparm.parm.capture.timeperframe.denominator,
            mapping_count, warmup_buffers, stats.count, (unsigned long long)stats.bytes);
    json_number(output, measured_seconds > 0 ? (double)stats.count / measured_seconds : NAN);
    fputs(",\n  \"arrival_interval_hz\": ", output);
    json_number(output, span_hz(stats.count, stats.first_arrival, stats.last_arrival));
    fputs(",\n  \"kernel_timestamp_interval_hz\": ", output);
    json_number(output, span_hz(stats.valid_timestamp_count, stats.first_timestamp, stats.last_timestamp));
    fprintf(output, ",\n  \"first_arrival_monotonic_ns\": %lld,\n  \"last_arrival_monotonic_ns\": %lld,\n"
                    "  \"first_kernel_timestamp_ns\": %lld,\n  \"last_kernel_timestamp_ns\": %lld,\n"
                    "  \"valid_kernel_timestamps\": %zu,\n  \"invalid_kernel_timestamps\": %llu,\n"
                    "  \"duplicate_timestamps\": %llu,\n  \"backward_timestamps\": %llu,\n"
                    "  \"first_kernel_sequence\": %u,\n  \"last_kernel_sequence\": %u,\n"
                    "  \"kernel_sequence_gap_units\": %llu,\n  \"kernel_sequence_duplicates\": %llu,\n"
                    "  \"kernel_sequence_backwards\": %llu,\n  \"v4l2_error_flag_buffers\": %llu,\n"
                    "  \"timestamp_flag_counts\": {\"monotonic\": %llu, \"copy\": %llu, \"unknown\": %llu},\n",
            (long long)stats.first_arrival, (long long)stats.last_arrival,
            (long long)stats.first_timestamp, (long long)stats.last_timestamp,
            stats.valid_timestamp_count, (unsigned long long)stats.invalid_timestamps,
            (unsigned long long)stats.timestamp_duplicates, (unsigned long long)stats.timestamp_backwards,
            stats.first_sequence, stats.last_sequence, (unsigned long long)stats.sequence_gaps,
            (unsigned long long)stats.sequence_duplicates, (unsigned long long)stats.sequence_backwards,
            (unsigned long long)stats.error_flag_buffers, (unsigned long long)stats.timestamp_monotonic,
            (unsigned long long)stats.timestamp_copy, (unsigned long long)stats.timestamp_unknown);
    fputs("  \"failure_stage\": ", output);
    if (stage) json_string(output, stage); else fputs("null", output);
    fprintf(output, ",\n  \"failure_errno\": %d,\n  \"failure_message\": ", saved_errno);
    if (stage) json_string(output, strerror(saved_errno)); else fputs("null", output);
    fprintf(output, ",\n  \"cleanup_ok\": %s,\n  \"sample\": {\"path\": ", cleanup_ok ? "true" : "false");
    if (sample_path) json_string(output, sample_path); else fputs("null", output);
    fprintf(output, ", \"saved\": %s, \"bytes\": %zu, \"kernel_sequence\": %u, \"kernel_timestamp_ns\": %lld},\n",
            sample_saved ? "true" : "false", sample_size, sample_sequence, (long long)sample_timestamp);
    fputs("  \"scope\": \"Pure MJPG/YUYV DQBUF; explicit S_FMT/S_PARM, then post-STREAMON optional power-line frequency "
          "followed by manual exposure SET+GET; "
          "no JPEG decode/inference. Manual condition is checked at measured-window boundaries, not per-frame sensor telemetry. "
          "Original controls restored and readback checked before close. No automatic retry of a failed condition. "
          "Rates are actual N/window and (N-1)/timestamp span, not negotiated 30 FPS. "
          "Kernel flags/sequence gaps are not USB packet error counters. Optional sample uses one bounded "
          "JPEG memory copy per measured buffer; JPEG file write happens after STREAMOFF.\",\n", output);
    fprintf(output, "  \"record_limit\": %d,\n  \"record_count\": %zu,\n  \"buffer_records\": [\n", MAX_RECORDS, stats.record_count);
    for (size_t index = 0; index < stats.record_count; ++index) {
        const struct record *record = &stats.records[index];
        fprintf(output, "    {\"arrival_monotonic_ns\": %lld, \"kernel_timestamp_ns\": ", (long long)record->arrival_ns);
        if (record->timestamp_ns >= 0) fprintf(output, "%lld", (long long)record->timestamp_ns); else fputs("null", output);
        fprintf(output, ", \"kernel_sequence\": %u, \"bytes\": %u, \"flags\": %u}%s\n",
                record->sequence, record->bytes, record->flags, index + 1 < stats.record_count ? "," : "");
    }
    fputs("  ]\n}\n", output);
    if (fclose(output) != 0) { perror("write report"); succeeded = false; }
    free(sample_data); free(stats.records);
    fprintf(stderr,"V4L2 buffers=%zu window=%.3fs actual_hz=%.3f arrival_span_hz=%.3f status=%s\n", stats.count,
           measured_seconds, measured_seconds > 0 ? stats.count / measured_seconds : NAN,
           span_hz(stats.count, stats.first_arrival, stats.last_arrival), succeeded ? "complete" : "failed_or_incomplete");
    if (stage) fprintf(stderr, "%s: %s\n", stage, strerror(saved_errno));
    return succeeded ? 0 : 2;
}



