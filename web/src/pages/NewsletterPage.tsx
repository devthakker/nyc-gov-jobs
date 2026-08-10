import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Check, Mail, RefreshCw } from "lucide-react";
import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import {
  APIError,
  getTracks,
  subscribeToNewsletter,
  type NewsletterSubscriptionRequest,
} from "../api/client";

export function NewsletterPage() {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [allTracks, setAllTracks] = useState(true);
  const [selectedTracks, setSelectedTracks] = useState<string[]>([]);
  const [consent, setConsent] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const tracksQuery = useQuery({
    queryKey: ["tracks", "all"],
    queryFn: ({ signal }) => getTracks(signal, true),
  });
  const subscription = useMutation({
    mutationFn: (request: NewsletterSubscriptionRequest) => subscribeToNewsletter(request),
  });

  const toggleTrack = (slug: string) => {
    setSelectedTracks((current) =>
      current.includes(slug) ? current.filter((item) => item !== slug) : [...current, slug],
    );
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError(null);
    if (!allTracks && selectedTracks.length === 0) {
      setFormError("Choose at least one career track, or select the full opportunity index.");
      return;
    }
    if (!consent) {
      setFormError("Please confirm that you want to receive the weekly dispatch.");
      return;
    }
    subscription.mutate({
      email,
      name: name.trim() || null,
      frequency: "weekly",
      all_tracks: allTracks,
      track_slugs: allTracks ? [] : selectedTracks,
      consent: true,
    });
  };

  if (subscription.isSuccess) {
    const preference = subscription.data.all_tracks
      ? "the full opportunity index"
      : subscription.data.tracks.map((track) => track.name).join(", ");
    return (
      <section className="dispatch-success" aria-live="polite">
        <div className="dispatch-success__mark"><Check size={34} aria-hidden="true" /></div>
        <span className="eyebrow">Dispatch confirmed</span>
        <h1>{subscription.data.created ? "You’re on the list." : "Your alerts are updated."}</h1>
        <p>
          We’ll send a weekly collection for <strong>{preference}</strong> to <strong>{subscription.data.email}</strong>.
        </p>
        <div className="dispatch-success__actions">
          <Link to="/"><ArrowLeft size={17} aria-hidden="true" /> Browse current jobs</Link>
          <button type="button" onClick={() => subscription.reset()}>
            <RefreshCw size={15} aria-hidden="true" /> Change preferences
          </button>
        </div>
      </section>
    );
  }

  const requestError = subscription.error instanceof APIError
    ? subscription.error.message
    : subscription.isError
      ? "We couldn’t save your subscription. Please try again."
      : null;

  return (
    <div className="dispatch-page">
      <section className="dispatch-hero">
        <Link className="dispatch-hero__back" to="/"><ArrowLeft size={16} /> Back to the index</Link>
        <span className="dispatch-hero__issue" aria-hidden="true">NY / WEEKLY</span>
        <div>
          <span className="eyebrow">The opportunity dispatch</span>
          <h1>Less searching.<br /><em>More direction.</em></h1>
          <p>A weekly edit of public jobs, sorted into the career paths that make sense for you.</p>
        </div>
        <aside>
          <Mail size={25} aria-hidden="true" />
          <strong>One useful note.</strong>
          <p>New openings, closing dates, listed pay, and direct links to the official posting.</p>
        </aside>
      </section>

      <section className="dispatch-form-section" aria-labelledby="dispatch-form-title">
        <div className="dispatch-form-intro">
          <span className="section-index">01 / Your dispatch</span>
          <h2 id="dispatch-form-title">Build your weekly brief.</h2>
          <p>Start broad or choose only the tracks you want. Submitting the same email later will update these preferences.</p>
          <dl>
            <div><dt>Cadence</dt><dd>Weekly</dd></div>
            <div><dt>Cost</dt><dd>Free</dd></div>
            <div><dt>Source</dt><dd>Public employer listings</dd></div>
          </dl>
        </div>

        <form className="dispatch-form" onSubmit={submit} noValidate>
          <fieldset className="dispatch-form__identity">
            <legend>Where should we send it?</legend>
            <label>
              <span>First name <small>Optional</small></span>
              <input autoComplete="given-name" maxLength={100} value={name} onChange={(event) => setName(event.target.value)} placeholder="Devin" />
            </label>
            <label>
              <span>Email address</span>
              <input required autoComplete="email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" />
            </label>
          </fieldset>

          <fieldset className="dispatch-form__preferences">
            <legend>What should be in your dispatch?</legend>
            <label className={allTracks ? "dispatch-choice is-selected" : "dispatch-choice"}>
              <input type="radio" name="scope" checked={allTracks} onChange={() => setAllTracks(true)} />
              <span><strong>The full opportunity index</strong><small>Every career track, in one weekly view.</small></span>
              <Check size={18} aria-hidden="true" />
            </label>
            <label className={!allTracks ? "dispatch-choice is-selected" : "dispatch-choice"}>
              <input type="radio" name="scope" checked={!allTracks} onChange={() => setAllTracks(false)} />
              <span><strong>Only my career tracks</strong><small>Make a focused brief from the options below.</small></span>
              <Check size={18} aria-hidden="true" />
            </label>

            {!allTracks && (
              <div className="dispatch-track-picker">
                {tracksQuery.isLoading && <p>Reading the career index…</p>}
                {tracksQuery.isError && <p>Career tracks are unavailable right now. Please retry.</p>}
                {tracksQuery.data?.map((track, index) => (
                  <label key={track.slug} className={selectedTracks.includes(track.slug) ? "is-selected" : ""}>
                    <input
                      type="checkbox"
                      checked={selectedTracks.includes(track.slug)}
                      onChange={() => toggleTrack(track.slug)}
                    />
                    <span aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
                    <strong>{track.name}</strong>
                    <small>{track.job_count} open now</small>
                  </label>
                ))}
              </div>
            )}
          </fieldset>

          <label className="dispatch-consent">
            <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
            <span>I agree to receive the weekly Job Tracks opportunity dispatch at this email address.</span>
          </label>

          {(formError || requestError) && <p className="dispatch-form__error" role="alert">{formError || requestError}</p>}

          <button className="dispatch-submit" type="submit" disabled={subscription.isPending}>
            {subscription.isPending ? "Saving your preferences…" : "Start my weekly dispatch"}
            {!subscription.isPending && <ArrowRight size={19} aria-hidden="true" />}
          </button>
          <p className="dispatch-form__fine-print">Your email is stored only for this local pilot. Subscriber records are not available through the public API.</p>
        </form>
      </section>
    </div>
  );
}
