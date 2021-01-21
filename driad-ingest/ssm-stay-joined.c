#include <stdio.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <ctype.h>
#include <errno.h>
#include <unistd.h>
#include <time.h>
#include <signal.h>

#include <mcrx/libmcrx.h>

struct sub_info {
  int total_packets;
  time_t start_time;
};

static volatile int stopping = 0;
static void
stopping_sighandler(int sig, siginfo_t *si, void *unused) {
  stopping = 1;
}


static int receive_cb(struct mcrx_packet* pkt) {
  unsigned int length = mcrx_packet_get_contents(pkt, 0);
  struct mcrx_subscription* sub = mcrx_packet_get_subscription(pkt);
  struct sub_info* info = (struct sub_info*)mcrx_subscription_get_userdata(sub);
  info->total_packets += 1;
  mcrx_packet_unref(pkt);
  pkt = NULL;

  if (stopping) {
    mcrx_subscription_leave(sub);
    return MCRX_RECEIVE_STOP_FD;
  }
  return MCRX_RECEIVE_CONTINUE;
}

int
main(int argc, char *argv[]) {
  if (argc != 4) {
    printf("usage: %s <source> <group> <port>", argv[0]);
    return EXIT_FAILURE;
  }

  const char* source = argv[1];
  const char* group = argv[2];
  const char* port_str = argv[3];
  int port = 0;
  int verbose = 0;
  int timeout_milliseconds=500;
  double msg_delay = 10.;
  int rc;
  int fail = 0;

  rc = sscanf(port_str, "%d", &port);
  if (rc != 1) {
    fprintf(stderr, "failed to read port from %s\n", port_str);
    fail = 1;
  } else {
    if (port < 1 || port > 0xffff) {
      fprintf(stderr, "port %d not a valid port (1-%d)\n", port, 0xffff);
      fail = 1;
    }
  }

  struct sigaction sa;
  sa.sa_flags = SA_SIGINFO;
  sigemptyset(&sa.sa_mask);
  sa.sa_sigaction = stopping_sighandler;
  if (sigaction(SIGTERM, &sa, NULL) == -1) {
    perror("sigaction(SIGTERM) failed");
    return EXIT_FAILURE;
  }
  if (sigaction(SIGHUP, &sa, NULL) == -1) {
    perror("sigaction(SIGHUP) failed");
    return EXIT_FAILURE;
  }
  if (sigaction(SIGINT, &sa, NULL) == -1) {
    perror("sigaction(SIGINT) failed");
    return EXIT_FAILURE;
  }
  if (sigaction(SIGQUIT, &sa, NULL) == -1) {
    perror("sigaction(SIGQUIT) failed");
    return EXIT_FAILURE;
  }

  struct mcrx_ctx *ctx;
  struct mcrx_subscription *sub = NULL;
  int err;
  struct sub_info info = {
    .total_packets=0,
    .start_time=time(0),
  };

  struct mcrx_subscription_config cfg = MCRX_SUBSCRIPTION_CONFIG_INIT;
  err = mcrx_subscription_config_pton(&cfg, source, group);
  if (err != 0) {
    fprintf(stderr, "subscription_config_pton failed\n");
    fail = 1;
  }

  if (fail) {
    return -1;
  }

  err = mcrx_ctx_new(&ctx);
  if (err != 0) {
    fprintf(stderr, "ctx_new failed\n");
    return EXIT_FAILURE;
  }
  int level = MCRX_LOGLEVEL_WARNING;
  if (verbose > 1) {
    level = MCRX_LOGLEVEL_DEBUG;
  } else if (verbose > 0) {
    level = MCRX_LOGLEVEL_INFO;
  }
  mcrx_ctx_set_log_priority(ctx, level);

  cfg.port = port;

  err = mcrx_subscription_new(ctx, &cfg, &sub);
  if (err != 0) {
    fprintf(stderr, "new subscription failed\n");
    mcrx_ctx_unref(ctx);
    return EXIT_FAILURE;
  }

  mcrx_subscription_set_userdata(sub, (intptr_t)&info);
  mcrx_subscription_set_receive_cb(sub, receive_cb);
  mcrx_ctx_set_wait_ms(ctx, timeout_milliseconds);

  err = mcrx_subscription_join(sub);
  if (err != 0) {
    fprintf(stderr, "subscription join failed\n");
    mcrx_subscription_unref(sub);
    mcrx_ctx_unref(ctx);
    return EXIT_FAILURE;
  }

  time_t last_msg_time = time(0);
  do {
    time_t now = time(0);
    double dur = difftime(now, last_msg_time);
    if (dur > msg_delay) {
      double total_dur = difftime(now, info.start_time);
      struct tm *info;
      last_msg_time = now;
      char tbuf[80];
      info = localtime(&now);
      strftime(tbuf,sizeof(tbuf),"%m-%d %H:%M:%S", info);
      printf("%s: joined to %s->%s for %gs\n", tbuf, source, group, total_dur);
    }
    err = mcrx_ctx_receive_packets(ctx);
  } while ((!err || err == MCRX_ERR_TIMEDOUT) && !stopping);

  if (err != MCRX_ERR_NOTHING_JOINED && err != MCRX_ERR_TIMEDOUT) {
    fprintf(stderr, "subscription receive failed: %s\n", strerror(errno));
    mcrx_subscription_unref(sub);
    mcrx_ctx_unref(ctx);
    return EXIT_FAILURE;
  }

  mcrx_subscription_unref(sub);
  mcrx_ctx_unref(ctx);
  time_t now = time(0);
  double dur = difftime(now, info.start_time);
  return EXIT_SUCCESS;
}


