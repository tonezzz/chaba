/* espusb - userspace CH340 serial + ESP32 ROM flasher over /dev/bus/usb
 *
 * Modes:
 *   espusb <usbdev> read [seconds]          - init CH340 @115200, dump console
 *   espusb <usbdev> flash <file.bin>        - reset into ROM bootloader via
 *                                             DTR/RTS, SLIP flash at offset 0
 *   espusb <usbdev> readsync [seconds]      - like read but at 115200 after a
 *                                             DTR/RTS download-mode reset
 *
 * No kernel driver required: talks USBDEVFS ioctls directly.
 * CH340 protocol replicated from Linux drivers/usb/serial/ch341.c.
 * ESP32 protocol = esptool SLIP stub protocol (ESP32 classic ROM).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <time.h>
#include <sys/ioctl.h>
#include <linux/usbdevice_fs.h>

#define EP_BULK_IN  0x82
#define EP_BULK_OUT 0x02
#define IFNUM       0
#define BAUD        115200

/* ---------- low-level usb ---------- */
static int ufd;

static int ctrl(int reqtype, int req, int val, int idx, void *data, int len, int timeout)
{
    struct usbdevfs_ctrltransfer t;
    memset(&t, 0, sizeof(t));
    t.bRequestType = reqtype; t.bRequest = req;
    t.wValue = val; t.wIndex = idx; t.wLength = len;
    t.timeout = timeout; t.data = data;
    return ioctl(ufd, USBDEVFS_CONTROL, &t);
}
static int ctrl_out(int req, int val, int idx)
{ return ctrl(0x40, req, val, idx, NULL, 0, 1000); }
static int ctrl_in(int req, int val, int idx, void *b, int len)
{ return ctrl(0xC0, req, val, idx, b, len, 1000); }

static int bulk(int ep, void *buf, int len, int timeout)
{
    struct usbdevfs_bulktransfer t;
    memset(&t, 0, sizeof(t));
    t.ep = ep; t.len = len; t.timeout = timeout; t.data = buf;
    return ioctl(ufd, USBDEVFS_BULK, &t);
}

/* ---------- ch340 ---------- */
static int ch341_baud(int baud)
{
    unsigned long factor = 1532620800UL / baud;
    int divisor = 3;
    while (factor > 0xfff0 && divisor) { factor >>= 3; divisor--; }
    factor = 0x10000 - factor;
    return ((int)(factor & 0xff00) | divisor) | 0x80;
}

static int ch341_init(int baud)
{
    unsigned char b[8];
    if (ctrl_in(0x5F, 0, 0, b, 2) < 0) { perror("read_version"); return -1; }
    fprintf(stderr, "[ch340] ver %02x %02x\n", b[0], b[1]);
    if (ctrl_out(0xA1, 0, 0) < 0) { perror("serial_init"); return -1; }
    if (ctrl_in(0x95, 0x2518, 0, b, 2) < 0) { perror("read_reg"); return -1; }
    if (ctrl_out(0x9A, 0x2518, 0x0050) < 0) { perror("init_lcr"); return -1; }
    int a = ch341_baud(baud);
    if (ctrl_out(0x9A, 0x1312, a) < 0) { perror("baud"); return -1; }
    if (ctrl_out(0x9A, 0x2518, 0x00C3) < 0) { perror("lcr"); return -1; } /* 8N1 rx|tx */
    fprintf(stderr, "[ch340] init ok baud=%d reg=0x%04x\n", baud, a & 0xffff);
    return 0;
}

static void ch341_modem(int dtr, int rts)
{
    int c = (dtr ? 0x20 : 0) | (rts ? 0x40 : 0);
    ctrl_out(0xA4, (~c) & 0xffff, 0);
}

static void msleep(int ms) { struct timespec t = { ms/1000, (ms%1000)*1000000L }; nanosleep(&t, NULL); }

/* esptool classic reset into download mode: DTR->IO0, RTS->EN (inverted on board) */
static void esp_enter_bootloader(void)
{
    ch341_modem(0, 1); msleep(100);   /* EN low */
    ch341_modem(1, 0); msleep(120);   /* IO0 low, EN high -> download boot */
    ch341_modem(0, 0); msleep(50);    /* release IO0 */
}
static void esp_reset_run(void)
{
    ch341_modem(0, 1); msleep(100);
    ch341_modem(0, 0); msleep(50);
}

/* ---------- SLIP ---------- */
static int slip_send(const uint8_t *data, int len)
{
    uint8_t buf[8192]; int o = 0;
    buf[o++] = 0xC0;
    for (int i = 0; i < len; i++) {
        uint8_t c = data[i];
        if (c == 0xC0) { buf[o++] = 0xDB; buf[o++] = 0xDC; }
        else if (c == 0xDB) { buf[o++] = 0xDB; buf[o++] = 0xDD; }
        else buf[o++] = c;
    }
    buf[o++] = 0xC0;
    int w = 0;
    while (w < o) {
        int r = bulk(EP_BULK_OUT, buf + w, o - w, 2000);
        if (r < 0) return r;
        w += r;
    }
    return 0;
}

/* read one SLIP frame into buf (returns payload len, -1 timeout) */
static int slip_recv(uint8_t *buf, int cap, int timeout_ms)
{
    uint8_t rb[512]; int n = 0, esc = 0, started = 0;
    long deadline = timeout_ms;
    while (deadline > 0) {
        int slice = deadline > 200 ? 200 : deadline;
        int r = bulk(EP_BULK_IN, rb, sizeof(rb), slice);
        deadline -= slice;
        if (r <= 0) continue;
        for (int i = 0; i < r; i++) {
            uint8_t c = rb[i];
            if (!started) { if (c == 0xC0) started = 1; continue; }
            if (c == 0xC0) return n;
            if (esc) { buf[n++] = (c == 0xDC) ? 0xC0 : 0xDD; esc = 0; continue; }
            if (c == 0xDB) { esc = 1; continue; }
            if (n < cap) buf[n++] = c;
        }
    }
    return -1;
}

/* send ESP command packet: dir=0, cmd, size(2le), value(4le), data */
static int esp_cmd(int cmd, const void *data, int dlen, uint32_t value)
{
    uint8_t p[2048]; int o = 0;
    p[o++] = 0x00; p[o++] = (uint8_t)cmd;
    p[o++] = dlen & 0xff; p[o++] = (dlen >> 8) & 0xff;
    p[o++] = value & 0xff; p[o++] = (value >> 8) & 0xff;
    p[o++] = (value >> 16) & 0xff; p[o++] = (value >> 24) & 0xff;
    if (data) memcpy(p + o, data, dlen);
    return slip_send(p, o + dlen);
}

/* wait for a response matching cmd; returns payload len; fills value */
static int esp_resp(int cmd, uint8_t *data, int cap, int timeout_ms, uint32_t *value)
{
    uint8_t f[2048];
    long left = timeout_ms;
    while (left > 0) {
        int n = slip_recv(f, sizeof(f), left > 500 ? 500 : left);
        left -= 500;
        if (n < 8) continue;
        if (f[0] != 0x01) continue;
        int sz = f[2] | (f[3] << 8);
        if (f[1] != (uint8_t)cmd) { fprintf(stderr, "[esp] resp for cmd 0x%02x (want 0x%02x)\n", f[1], cmd); continue; }
        if (value) *value = f[4] | (f[5] << 8) | (f[6] << 16) | ((uint32_t)f[7] << 24);
        int dlen = n - 8 < sz ? n - 8 : sz;
        if (dlen > cap) dlen = cap;
        memcpy(data, f + 8, dlen > 0 ? dlen : 0);
        /* status check: last data byte(s): [status][error]? ESP32: data[-4..-1]? */
        if (dlen >= 2) {
            int st = data[dlen - 2], er = data[dlen - 1];
            if (st != 0) { fprintf(stderr, "[esp] cmd 0x%02x status=%d err=%d\n", cmd, st, er); return -2; }
        }
        return dlen;
    }
    return -1;
}

static int esp_sync(void)
{
    uint8_t s[36]; s[0] = 0x07; s[1] = 0x07; s[2] = 0x12; s[3] = 0x20;
    memset(s + 4, 0x55, 32);
    uint8_t rd[256]; uint32_t v;
    for (int i = 0; i < 8; i++) {
        esp_cmd(0x08, s, 36, 0);
        int n = esp_resp(0x08, rd, sizeof(rd), 400, &v);
        if (n >= 0) { fprintf(stderr, "[esp] sync ok\n"); return 0; }
    }
    return -1;
}

/* ---------- read mode ---------- */
static int do_read(int secs, int enter_bl)
{
    if (ch341_init(BAUD)) return 1;
    if (enter_bl) { fprintf(stderr, "[esp] entering download mode\n"); esp_enter_bootloader(); }
    uint8_t b[512]; time_t end = time(NULL) + secs;
    while (time(NULL) < end) {
        int r = bulk(EP_BULK_IN, b, sizeof(b), 400);
        if (r > 0) { fwrite(b, 1, r, stdout); fflush(stdout); }
    }
    fprintf(stderr, "\n[read done]\n");
    return 0;
}

/* ---------- flash ---------- */
static int do_flash(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f) { perror("open image"); return 1; }
    fseek(f, 0, SEEK_END); long sz = ftell(f); fseek(f, 0, SEEK_SET);
    uint8_t *img = malloc(sz);
    if (fread(img, 1, sz, f) != (size_t)sz) { perror("read"); return 1; }
    fclose(f);
    fprintf(stderr, "[flash] image %ld bytes\n", sz);

    if (ch341_init(BAUD)) return 1;
    fprintf(stderr, "[esp] entering download mode\n");
    esp_enter_bootloader();
    msleep(200);
    /* flush stale rx */
    uint8_t junk[512]; while (bulk(EP_BULK_IN, junk, sizeof(junk), 30) > 0) {}

    if (esp_sync()) { fprintf(stderr, "[esp] sync FAILED\n"); return 2; }

    uint8_t rd[64]; uint32_t v;
    uint8_t spi[8] = {0};
    esp_cmd(0x0D, spi, 8, 0);                     /* SPI_ATTACH (needed by ESP32 ROM) */
    int n = esp_resp(0x0D, rd, sizeof(rd), 3000, &v);
    fprintf(stderr, "[esp] spi_attach resp=%d\n", n);

    const int BS = 1024;
    int nblk = (sz + BS - 1) / BS;
    uint32_t hdr[4] = { (uint32_t)sz, (uint32_t)nblk, BS, 0 };
    esp_cmd(0x02, hdr, 16, 0);                    /* FLASH_BEGIN */
    n = esp_resp(0x02, rd, sizeof(rd), 90000, &v); /* erase of 1.3MB can take a while */
    if (n < 0) { fprintf(stderr, "[esp] flash_begin failed\n"); return 3; }
    fprintf(stderr, "[esp] flash_begin ok (%d blocks)\n", nblk);

    for (int i = 0; i < nblk; i++) {
        int chunk = sz - i * BS > BS ? BS : sz - i * BS;
        uint8_t pkt[8 + BS];
        uint8_t cs = 0xEF;
        for (int j = 0; j < chunk; j++) cs ^= img[i * BS + j];
        uint32_t h[4] = { (uint32_t)chunk, (uint32_t)i, 0, (uint32_t)(i * BS) };
        memcpy(pkt, h, 16);
        memcpy(pkt + 16, img + i * BS, chunk);
        esp_cmd(0x03, pkt, 16 + chunk, cs);       /* FLASH_DATA, checksum as value */
        n = esp_resp(0x03, rd, sizeof(rd), 10000, &v);
        if (n < 0) { fprintf(stderr, "[esp] flash_data blk %d failed\n", i); return 4; }
        if (i % 100 == 0) fprintf(stderr, "[flash] %d/%d\r", i, nblk);
    }
    fprintf(stderr, "[flash] data done          \n");

    uint32_t zero = 0;
    esp_cmd(0x04, &zero, 4, 0);                   /* FLASH_END: reboot */
    esp_resp(0x04, rd, sizeof(rd), 3000, &v);
    fprintf(stderr, "[esp] flash_end sent, resetting\n");
    esp_reset_run();
    fprintf(stderr, "[flash] DONE\n");
    return 0;
}

int main(int argc, char **argv)
{
    if (argc < 3) { fprintf(stderr, "usage: espusb <usbdev> read [secs]|readsync [secs]|flash <file>\n"); return 64; }
    ufd = open(argv[1], O_RDWR);
    if (ufd < 0) { perror("open usbdev"); return 1; }
    int ifn = IFNUM;
    if (ioctl(ufd, USBDEVFS_CLAIMINTERFACE, &ifn) < 0) { perror("claim"); return 1; }

    if (!strcmp(argv[2], "read")) return do_read(argc > 3 ? atoi(argv[3]) : 10, 0);
    if (!strcmp(argv[2], "readsync")) return do_read(argc > 3 ? atoi(argv[3]) : 10, 1);
    if (!strcmp(argv[2], "flash") && argc > 3) return do_flash(argv[3]);
    fprintf(stderr, "bad args\n");
    return 64;
}
