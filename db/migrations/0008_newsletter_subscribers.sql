CREATE TABLE newsletter_subscribers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email text NOT NULL UNIQUE,
    name text,
    status text NOT NULL DEFAULT 'subscribed',
    frequency text NOT NULL DEFAULT 'weekly',
    all_tracks boolean NOT NULL DEFAULT true,
    consented_at timestamptz NOT NULL,
    subscribed_at timestamptz NOT NULL DEFAULT now(),
    unsubscribed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (email = lower(email)),
    CHECK (position('@' IN email) > 1),
    CHECK (name IS NULL OR btrim(name) <> ''),
    CHECK (status IN ('subscribed', 'unsubscribed')),
    CHECK (frequency IN ('weekly')),
    CHECK ((status = 'subscribed' AND unsubscribed_at IS NULL)
        OR (status = 'unsubscribed' AND unsubscribed_at IS NOT NULL))
);

CREATE INDEX newsletter_subscribers_delivery_idx
    ON newsletter_subscribers(status, frequency)
    WHERE status = 'subscribed';

CREATE TABLE newsletter_subscriber_tracks (
    subscriber_id uuid NOT NULL
        REFERENCES newsletter_subscribers(id) ON DELETE CASCADE,
    track_id uuid NOT NULL REFERENCES tracks(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (subscriber_id, track_id)
);

CREATE INDEX newsletter_subscriber_tracks_track_idx
    ON newsletter_subscriber_tracks(track_id, subscriber_id);

CREATE TRIGGER newsletter_subscribers_set_updated_at
BEFORE UPDATE ON newsletter_subscribers
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE newsletter_subscribers IS
    'Private delivery preferences. This table is never exposed through a list endpoint.';
COMMENT ON COLUMN newsletter_subscribers.all_tracks IS
    'When true, an empty track join means send opportunities from every active track.';
