from transformers import pipeline
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np

classifier = pipeline("zero-shot-classification", model="joeddav/xlm-roberta-large-xnli")

def check_hof_msg(discord_msg: str, label: str = "confirm attendance"):
    if str is None or str == "":
        return 0

    hof_result = classifier(discord_msg, label)['scores'][0]
    return hof_result


if __name__ == '__main__':
    filter_messages = [
        "Er der nogen der er klar til at spille Apex Legends?",
        "Skal vi ramme virksomheden kl 20? Helst før",
        "Skal vi ramme virksomheden kl 19?",
        "Office kl 20?",
        "Gutter, vi skal spille perfect heist i dag. Skal vi sige kl 20?",
        "Skal vi sige kl 19:30 med perfect heist?",
    ]

    correct_messages = [
        "-1000 aura",
        ":joyyy:",
        "The god gamer gambit",
        "Håber luffy er med i spillet",
    ]

    labels = [
        "play games",
        "check readiness",
        "check readiness for playing games",
        "decide time or date",
        "confirm attendance",
    ]

    cutoff_threshold = 0.97
    labels_summarized = {}

    def llm_evaluate(label: str = "confirm attendance", plot_confusion_matrix = False):
        print("\nEvaluating LLM for label:", label)

        tp = 0
        tn = 0
        fp = 0
        fn = 0

        for message in filter_messages:
            result = classifier(message, label)

            if any(score>cutoff_threshold for score in result['scores']):
                print('\033[92m',result)
                tp += 1
            else:
                print('\033[91m',result)
                fn += 1

        for message in correct_messages:
            result = classifier(message, label)

            if any(score > cutoff_threshold for score in result['scores']):
                print('\033[92m', result)
                fp += 1
            else:
                print('\033[91m', result)
                tn += 1

        conf_matrix = np.array([[tn, fp],
                                [fn, tp]])

        precision = tp / (tp + fp)
        recall = tp / (tp + fn)
        accuracy = (tp + tn) / (tp + tn + fp + fn)

        print("\033[0m")  # Resetting color formatting to default
        print(conf_matrix)

        labels_summarized[label] = {"Accuracy": accuracy, "Precision": precision, "Recall": recall}

        if plot_confusion_matrix:
            plt.figure(figsize=(6, 5))
            plt.title(f'LLM with label: {label}')
            sns.heatmap(conf_matrix, annot=True, fmt='d', cmap='Blues',
                        xticklabels=['Predicted Negative', 'Predicted Positive'],
                        yticklabels=['Actual Negative', 'Actual Positive'])
            plt.title('Confusion Matrix')
            plt.xlabel('Predicted Labels')
            plt.ylabel('True Labels')
            plt.show()


    for candidate_label in labels:
        llm_evaluate(candidate_label)

    for label_eval in labels_summarized:
        print("Label:", label_eval, labels_summarized[label_eval])

