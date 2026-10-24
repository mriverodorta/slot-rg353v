/* Fixed RG353V RK817 analog routing. No PCM, polling timer or desktop audio stack. */
#include <alsa/asoundlib.h>
#include <errno.h>
#include <fcntl.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#define READY "/run/slot-speaker.ready"
struct control {
    snd_ctl_elem_info_t *info;
    snd_ctl_elem_value_t *value;
    unsigned int numid;
};
static int bind_control(snd_ctl_t *ctl, struct control *c,
                        snd_ctl_elem_iface_t iface, const char *name,
                        snd_ctl_elem_type_t type, unsigned int count)
{
    int rc = snd_ctl_elem_info_malloc(&c->info);
    if (rc < 0) return rc;
    rc = snd_ctl_elem_value_malloc(&c->value);
    if (rc < 0) return rc;
    snd_ctl_elem_info_set_interface(c->info, iface);
    snd_ctl_elem_info_set_name(c->info, name);
    rc = snd_ctl_elem_info(ctl, c->info);
    if (rc < 0) return rc;
    if (snd_ctl_elem_info_get_type(c->info) != type ||
        snd_ctl_elem_info_get_count(c->info) != count) return -EINVAL;
    c->numid = snd_ctl_elem_info_get_numid(c->info);
    snd_ctl_elem_value_set_numid(c->value, c->numid);
    return 0;
}
static void free_control(struct control *c)
{
    if (c->info) snd_ctl_elem_info_free(c->info);
    if (c->value) snd_ctl_elem_value_free(c->value);
}
static int item(snd_ctl_t *ctl, struct control *mux, const char *name)
{
    unsigned int count = snd_ctl_elem_info_get_items(mux->info);
    for (unsigned int i = 0; i < count; i++) {
        snd_ctl_elem_info_set_item(mux->info, i);
        int rc = snd_ctl_elem_info(ctl, mux->info);
        if (rc < 0) return rc;
        if (!strcmp(snd_ctl_elem_info_get_item_name(mux->info), name)) return (int)i;
    }
    return -EINVAL;
}
static int state(snd_ctl_t *ctl, struct control *jack, struct control *mux,
                 bool *plugged, unsigned int *route)
{
    int rc = snd_ctl_elem_read(ctl, jack->value);
    if (rc < 0) return rc;
    *plugged = snd_ctl_elem_value_get_boolean(jack->value, 0) != 0;
    rc = snd_ctl_elem_read(ctl, mux->value);
    if (rc < 0) return rc;
    *route = snd_ctl_elem_value_get_enumerated(mux->value, 0);
    return 0;
}
static int sync_route(snd_ctl_t *ctl, struct control *jack, struct control *mux,
                      int hp, int spk)
{
    bool plugged;
    unsigned int route;
    int rc = state(ctl, jack, mux, &plugged, &route);
    if (rc < 0) return rc;
    unsigned int wanted = (unsigned int)(plugged ? hp : spk);
    if (route != wanted) {
        snd_ctl_elem_value_set_enumerated(mux->value, 0, wanted);
        rc = snd_ctl_elem_write(ctl, mux->value);
        if (rc < 0) return rc;
        if (snd_ctl_elem_read(ctl, mux->value) < 0 ||
            snd_ctl_elem_value_get_enumerated(mux->value, 0) != wanted) return -EIO;
        printf("RK817 playback: %s\n", plugged ? "headphones" : "speaker");
        fflush(stdout);
    }
    return 0;
}
int main(int argc, char **argv)
{
    bool status = argc == 2 && !strcmp(argv[1], "--status");
    bool once = argc == 2 && !strcmp(argv[1], "--once");
    if (argc > 1 && !status && !once) {
        fprintf(stderr, "Usage: slot-audio-route [--status|--once]\n");
        return 2;
    }
    snd_ctl_t *ctl = NULL;
    struct control jack = {0}, mux = {0}, master = {0};
    snd_ctl_event_t *event = NULL;
    int rc;
    if (!status) unlink(READY);
    rc = snd_ctl_open(&ctl, "hw:rk817int", 0);
    if (rc < 0) goto done;
    rc = bind_control(ctl, &jack, SND_CTL_ELEM_IFACE_CARD, "Headphones Jack",
                      SND_CTL_ELEM_TYPE_BOOLEAN, 1);
    if (rc < 0) goto done;
    rc = bind_control(ctl, &mux, SND_CTL_ELEM_IFACE_MIXER, "Playback Mux",
                      SND_CTL_ELEM_TYPE_ENUMERATED, 1);
    if (rc < 0) goto done;
    int hp = item(ctl, &mux, "HP"), spk = item(ctl, &mux, "SPK");
    if (hp < 0 || spk < 0) { rc = -EINVAL; goto done; }
    if (status) {
        bool plugged;
        unsigned int route;
        rc = state(ctl, &jack, &mux, &plugged, &route);
        if (rc >= 0) printf("{\"headphones\":%s,\"route\":\"%s\",\"correct\":%s}\n",
            plugged ? "true" : "false", route == (unsigned int)hp ? "HP" :
            route == (unsigned int)spk ? "SPK" : "unknown",
            route == (unsigned int)(plugged ? hp : spk) ? "true" : "false");
        goto done;
    }
    rc = snd_ctl_subscribe_events(ctl, 1);
    if (rc < 0) goto done;
    rc = sync_route(ctl, &jack, &mux, hp, spk);
    if (rc < 0) goto done;
    rc = bind_control(ctl, &master, SND_CTL_ELEM_IFACE_MIXER, "Master Playback Volume",
                      SND_CTL_ELEM_TYPE_INTEGER, 2);
    if (rc < 0) goto done;
    /* Slot already owns separate software speaker/headphone volume and mute. */
    long maximum = snd_ctl_elem_info_get_max(master.info);
    if (maximum != 255) { rc = -EINVAL; goto done; }
    for (unsigned int i = 0; i < 2; i++)
        snd_ctl_elem_value_set_integer(master.value, i, maximum);
    rc = snd_ctl_elem_write(ctl, master.value);
    if (rc < 0) goto done;
    int ready = open(READY, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
    if (ready < 0) { rc = -errno; goto done; }
    close(ready);
    if (once) { rc = 0; goto done; }
    rc = snd_ctl_event_malloc(&event);
    if (rc < 0) goto done;
    for (;;) {
        /* Blocks until a control changes: no periodic wakeups or shell calls. */
        rc = snd_ctl_read(ctl, event);
        if (rc == -EINTR) continue;
        if (rc < 0) break;
        if (snd_ctl_event_get_type(event) != SND_CTL_EVENT_ELEM) continue;
        unsigned int numid = snd_ctl_event_elem_get_numid(event);
        if (numid != jack.numid && numid != mux.numid) continue;
        if (snd_ctl_event_elem_get_mask(event) == SND_CTL_EVENT_MASK_REMOVE) {
            rc = -ENODEV; break;
        }
        rc = sync_route(ctl, &jack, &mux, hp, spk);
        if (rc < 0) break;
    }
done:
    if (rc < 0) {
        fprintf(stderr, "RK817 routing: %s\n", snd_strerror(rc));
        if (!status) unlink(READY);
    }
    if (event) snd_ctl_event_free(event);
    free_control(&master); free_control(&mux); free_control(&jack);
    if (ctl) snd_ctl_close(ctl);
    return rc < 0 ? 1 : 0;
}
